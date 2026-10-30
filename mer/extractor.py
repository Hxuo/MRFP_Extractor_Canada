"""Template-independent, evidence-oriented native PDF ratio extractor with optional OCR."""
import re, io, hashlib, logging
from datetime import datetime
from dataclasses import dataclass,asdict
import pymupdf

LOG=logging.getLogger(__name__)
METRICS={'MER':r'\bmanagement\s+expense\s+ratios?\b|\bmer\b','TER':r'\btrading\s+expense\s+ratios?\b|\bter\b','PTR':r'\bportfolio\s+turnover\s+(?:rate|ratio)\b'}
YEAR=re.compile(r'\b(?:20[0-3]\d)\b')
NUM=re.compile(r'^\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\)?(?:\s*\([a-z0-9]+\))?$|^-?\d+(?:\.\d+)?%?(?:\s*\([a-z0-9]+\))?$',re.I)

CLASSES=re.compile(
 r'\bETF\s+Series\b'
 r'|\b(?:series|class)\s+[A-Z0-9][A-Z0-9-]*\b'
 r'|\b(?:investor\s*/\s*advisor|investor|advisor)\s+series\b'
 r'|\bETF\s+units\b',
 re.I
)


def clean(v):return re.sub(r'\s+',' ',str(v).replace('\xa0',' ')).strip()
def canonical(v):return clean(v).casefold()
def to_number(v):
 v=clean(v).replace(' ','').replace(',','')
 v=re.sub(r'\([a-z0-9]+\)$','',v,flags=re.I).strip()
 if v in ('—','–','-','N/A','n/a','NA'):return None
 v=v.replace('%','')
 if v.startswith('(') and v.endswith(')'): v='-'+v[1:-1]
 try:return float(v)
 except ValueError:return None

def metric_kind(label):
 t=canonical(label)
 for metric,pattern in METRICS.items():
  if re.search(pattern,t):
   if metric=='MER':
    if re.search(r'\bbefore\s+(?:tax(?:es)?|waiv\w*|absor\w*|allocat\w*)',t):return None,None
    if 'before allocation' in t:return None,None
    aft=t.split('after',1)[-1] if 'after' in t else ''
    flags=[bool(re.search(p,aft)) for p in (r'tax',r'waiv',r'absor')]
    priority=0 if sum(flags)>=2 else (1 if flags[0] else 2 if flags[1] else 3 if flags[2] else 4)
    return metric,priority
   return metric,0
 return None,None

@dataclass
class Item:
 text:str;x0:float;y0:float;x1:float;y1:float
 @property
 def cx(self):return (self.x0+self.x1)/2
 @property
 def cy(self):return (self.y0+self.y1)/2

def page_items(page):
 return [Item(clean(w[4]),*map(float,w[:4])) for w in page.get_text('words') if clean(w[4])]

def lines(items,tol=3.0):
 # center-y grouping, restrict to rows on the same horizontal band
 out=[]
 for w in sorted(items,key=lambda z:(z.cy,z.x0)):
  best=min(out,key=lambda r:abs(r['y']-w.cy),default=None)
  if best is None or abs(best['y']-w.cy)>tol:
   out.append({'y':w.cy,'words':[w]})
  else:
   best['words'].append(w)
   best['y']=sum(q.cy for q in best['words'])/len(best['words'])
 for r in out:
  r['words'].sort(key=lambda w:w.x0)
  r['text']=clean(' '.join(w.text for w in r['words']))
 return sorted(out,key=lambda r:r['y'])


def find_years(row):
 found=[]
 for w in row['words']:
  m=re.fullmatch(
   r'(20[0-3]\d)(?:\s*(?:\([0-9a-z]+\)|[*†‡]+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+))?',
   w.text,
   re.I
  )
  if m:
   found.append((int(m.group(1)),w.cx))
 return found

def find_years(row):
 found=[]
 for w in row['words']:
  m=re.fullmatch(
   r'(20[0-3]\d)(?:\s*(?:\([0-9a-z]+\)|[*†‡]+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+))?',
   w.text,
   re.I
  )
  if m:
   found.append((int(m.group(1)),w.cx))
 return found


def candidates_on_row(row,anchor_x=None,max_value=100):
 result=[]
 year_positions=[x for _,x in find_years(row)]
 for w in row['words']:
  v=to_number(w.text)
  if v is None or not (0<=v<=max_value):
   continue
  if any(abs(w.cx-x)<0.1 for x in year_positions):
   continue
  if anchor_x is not None and w.cx<=anchor_x:
   continue
  result.append((w,v))
 return result


def labels_on_rows(rows):
 found=[]
 for i,r in enumerate(rows):
  text=r['text']; k,priority=metric_kind(text)
  if k:
   matches=list(re.finditer(METRICS[k],text,re.I))
   if matches:found.append((i,k,priority))
 return found

def heading_at(rows,idx,prior,default):
 for j in range(idx,-1,-1):
  if idx-j>prior:break
  line=rows[j]['text']
  m=CLASSES.search(line)
  if m:
   v=clean(m.group());return re.sub(r'\s+',' ',v)
 return default

 
def extract_stacked_ratio_table(page, pagenum, fund):
    """Read year-as-rows tables with multi-line MER/TER/PTR headers."""
    rows = lines(page_items(page))

    for i, row in enumerate(rows):
        header_rows = rows[i:i + 5]

        # Require an actual table header rather than a narrative paragraph.
        words = [w for r in header_rows for w in r["words"]]

        mer = [
            w for w in words
            if re.sub(r"[^a-z]", "", w.text.lower()) == "mer"
        ]
        ter = [
            w for w in words
            if re.sub(r"[^a-z]", "", w.text.lower()) == "ter"
        ]
        portfolio = [
            w for w in words
            if re.fullmatch(r"portfolio", w.text, re.I)
        ]
        turnover = [
            w for w in words
            if re.fullmatch(r"turnover", w.text, re.I)
        ]

        if not (mer and ter and portfolio and turnover):
            continue

        ptr = next(
            (
                w for w in turnover
                if any(
                    abs(w.cy - p.cy) < 15
                    and 0 < w.cx - p.cx < 110
                    for p in portfolio
                )
            ),
            None
        )

        if ptr is None:
            continue

        # Prefer the quoted acronym, e.g. ("MER"), rather
        # than the separate "MER before waivers" column.
        anchors = {
            "MER": next(
                (w.cx for w in mer if "(" in w.text),
                mer[0].cx
            ),
            "TER": next(
                (w.cx for w in ter if "(" in w.text),
                ter[0].cx
            ),
            "PTR": ptr.cx
        }

        if not (
            anchors["MER"] + 20 < anchors["TER"]
            and anchors["TER"] + 20 < anchors["PTR"]
        ):
            continue

        found = []

        for j in range(i + 1, len(rows)):
            r = rows[j]

            if r["y"] - row["y"] > page.rect.height * 0.68:
                break

            if not re.search(
                r"\b(?:Jun|June|Dec|December|Mar|March|Sep|Sept|September)\b",
                r["text"],
                re.I
            ):
                continue

            yrs = find_years(r)
            if not yrs:
                continue

            year, date_x = yrs[0]
            numbers = candidates_on_row(
                r,
                anchor_x=date_x + 20
            )

            if len(numbers) < 3:
                continue

            class_name = heading_at(rows, j, 9, fund)

            for metric, x in anchors.items():
                w, value = min(
                    numbers,
                    key=lambda entry: abs(entry[0].cx - x)
                )

                if abs(w.cx - x) > 38:
                    continue

                found.append({
                    "class_name": class_name,
                    "year": year,
                    "metric": metric,
                    "value": value,
                    "source": metric + " (stacked table header)",
                    "priority": 4 if metric == "MER" else 0,
                    "page": pagenum,
                    "x": round(w.cx, 1),
                    "y": round(w.cy, 1),
                    "method": "native"
                })

        if found:
            return found

    return []


def extract_native(page,pagenum,fund):
 items=page_items(page)
 if not items:return [],False
 output=[]; groups=[items]
 # Split vertical columns only where true independent regions exist (e.g. Purpose dual side by side)
 # Avoid splitting generic wide tables whose metric values span page width.
 allrows=lines(items)
 halves=[ [w for w in items if w.cx<page.rect.width/2], [w for w in items if w.cx>=page.rect.width/2] ]
 full_metric_count=sum(metric_kind(r['text'])[0] is not None for r in allrows)
 if not any(re.search(r'\bDec\.?\s+31',r['text'],re.I) for r in allrows) and all(halves) and sum(sum(metric_kind(r['text'])[0] is not None for r in lines(h)) for h in halves)>=max(3,full_metric_count+2):
  groups=halves
 for group in groups:
  rows=lines(group)
  for i,kind,priority in labels_on_rows(rows):
   row=rows[i]
   if len(row['words'])<2:continue
   # The label is the leading words; numbers only appear to its right.
   match=re.search(METRICS[kind],row['text'],re.I)
   words=row['words']; start=next((w.x0 for w in words if re.search(r'management|trading|portfolio|\bmer\b|\bter\b',w.text,re.I)),words[0].x0)
   
   vals=[(w,v) for w,v in candidates_on_row(
     row,
     max_value=1000 if kind=='PTR' else 100
    ) if w.x0>start+25]

   if not vals:continue
   # Header can be several lines above. Select nearest row with >=2 years.
   header=None
   for j in range(i-1,max(-1,i-48),-1):
    ys=find_years(rows[j])
    if len(ys)>=2:
     header=ys;break
   # Vertical tables: year appears on same line as values; metric header at top.
   if header:
    # Pair numeric values by monotonically increasing X coordinate with sorted year positions.
    vv=sorted(vals,key=lambda z:z[0].cx)
    yy=sorted(header,key=lambda z:z[1])
    # sometimes same line includes numeric footnote e.g. (6) -- should not shift year/value positions
    if len(vv)==len(yy):pairs=list(zip(yy,vv))
    else:
     pairs=[];used=set()
     for yr,x in yy:
      options=sorted(((abs(w.cx-x),index,w,v) for index,(w,v) in enumerate(vv) if index not in used),key=lambda z:z[0])
      if options and options[0][0]<max(34,page.rect.width*0.065):
       _,index,w,v=options[0];used.add(index);pairs.append(((yr,x),(w,v)))
    label=heading_at(rows,i,65,fund)
    if re.search(r'\d{4}.*report of fund performance',label,re.I):label=fund
    for (yr,_),(w,v) in pairs:
     output.append({'class_name':label,'year':yr,'metric':kind,'value':v,'source':row['text'][:180], 'priority':priority,'page':pagenum,'x':round(w.cx,1),'y':round(w.cy,1),'method':'native'})
   else:
    # Row-wise tables. Header lists metric labels and the year occurs in data row, not necessarily this row.
    pass
  # Multi-line column headers: aggregate words vertically in narrow column zones.
  # E.g. RBC's "Management" above "Expense Ratio" and "Portfolio" above "Turnover Rate".
  for i,r in enumerate(rows):
   if not re.search(r'\b(?:management|trading|portfolio)\b',r['text'],re.I):continue
   if find_years(r):continue
   base=r['y']
   top=[a for a in rows if base-2<=a['y']<=base+20]
   metric_columns=[]
   for word in r['words']:
    stem=word.text.lower()
    if stem not in ('management','trading','portfolio'):continue
    kind={'management':'MER','trading':'TER','portfolio':'PTR'}[stem]
    # Verify second-line label in the same column; avoids narrative false positives.
    below=' '.join(w.text for row_ in top for w in row_['words'] if row_['y']>base+3 and abs(w.cx-word.cx)<28).lower()
    if not re.search('expense|turnover|ratio|rate',below):continue
    metric_columns.append((kind,4 if kind=='MER' else 0,word.cx))
   if not metric_columns:continue
   for data_row in rows[i+1:]:
    if data_row['y']>base+270:break
    if not re.search(r'\b(?:Dec\.?|June|Jun\.?)\b',data_row['text'],re.I):continue
    yrs=find_years(data_row)
    if not yrs:continue
    yr=yrs[0][0]
    vals=[(w,v) for w,v in candidates_on_row(data_row) if w.cx>yrs[0][1]+20]
    cname=heading_at(rows,rows.index(data_row),8,fund)
    for kind,prio,x in metric_columns:
     if not vals:continue
     w,v=min(vals,key=lambda z:abs(z[0].cx-x))
     if abs(w.cx-x)>30:continue
     output.append({'class_name':cname,'year':yr,'metric':kind,'value':v,'source':kind,'priority':prio,'page':pagenum,'x':round(w.cx,1),'y':round(w.cy,1),'method':'native'})
  # Vertical table special handling: section header fields and year rows.
  headers=[]
  for i in range(len(rows)):
   if not re.search(r'management\s+expense|trading\s+expense|portfolio\s+turnover',rows[i]['text'],re.I):continue
   if find_years(rows[i]):continue
   for k in range(3):
    phrase=clean(' '.join(rows[z]['text'] for z in range(max(0,i-k),i+1)))
    kind,priority=metric_kind(phrase)
    if kind:
     headwords=rows[i]['words']; x=sum(w.cx for w in headwords)/len(headwords)
     headers.append((kind,priority,x,rows[i]['y']))
     break
  if headers:
   # actual word matching uses relative grid order of numeric year lines (e.g. RBC)
   known=[]
   for i,r in enumerate(rows):
    yr=find_years(r)
    if not yr or not ('20' in r['text']):continue
    if re.search(r'\b(?:Dec\.?|June|Jun\.?|Mar\.?|Sept\.?|Sep\.?|December)\b',r['text'],re.I) and len(candidates_on_row(r))>=3:
     year=yr[0][0]; vals=[(w,v) for w,v in candidates_on_row(r) if w.x0>max(y[1] for y in yr)]
     if not vals:continue
     cname=heading_at(rows,i,10,fund)
     for kind,prio,hx,hy in headers:
      if hy>r['y']:continue
      best=min(vals,key=lambda a:abs(a[0].cx-hx))
      if abs(best[0].cx-hx)>32:continue
      w,value=best
      output.append({'class_name':cname,'year':year,'metric':kind,'value':value,'source':kind,'priority':prio,'page':pagenum,'x':round(w.cx,1),'y':round(w.cy,1),'method':'native'})
  output.extend(extract_stacked_ratio_table(page,pagenum,fund))
 return output,True

def ocr_items(page, dpi=220):
 try:
  from paddleocr import PaddleOCR
 except ImportError as e:raise RuntimeError('PaddleOCR unavailable. Install optional requirements from requirements-ocr.txt') from e
 # Initialized once, only on selected problematic pages
 global _PADDLE
 if _PADDLE is None:
  _PADDLE=PaddleOCR(lang='en',use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False)
 import numpy as np
 pix=page.get_pixmap(dpi=dpi,alpha=False)
 arr=np.frombuffer(pix.samples,dtype=np.uint8).reshape((pix.height,pix.width,3))
 res=_PADDLE.predict(arr)
 out=[]
 for pred in res:
  data=pred.json if hasattr(pred,'json') else pred
  data=data.get('res',data)
  for txt,poly in zip(data.get('rec_texts',[]),data.get('rec_polys',[])):
   try:
    x0=min(float(p[0]) for p in poly);x1=max(float(p[0]) for p in poly)
    y0=min(float(p[1]) for p in poly);y1=max(float(p[1]) for p in poly)
    scale=72/dpi
    out.append(Item(clean(txt),x0*scale,y0*scale,x1*scale,y1*scale))
   except (TypeError,ValueError,IndexError):continue
 return out
_PADDLE=None


def detect_fund_name(doc):
    """Detect fund names from cover text and validated PDF metadata."""

    endings = re.compile(
        r'\b(?:fund|class|etf|portfolio)\s*$',
        re.I
    )

    generic = re.compile(
        r'management report|fund performance|financial highlights|'
        r'financial statements|annual report|semi.annual report|'
        r'portfolio turnover|expense ratio|trading expense|'
        r'table of contents|corporate profile|'
        r'investment objectives|investment strategies',
        re.I
    )

    def valid_name(value):
        name = clean(value).strip(' :-–—|')
                # Bulleted contents and navigation lists are not fund names.
        if re.search(r'[•●▪◦·∙‣⁃]', name):
            return False

        if not (8 <= len(name) <= 110):
            return False

        if not endings.search(name):
            return False

        if generic.search(name):
            return False

        if not (2 <= len(name.split()) <= 12):
            return False

        if re.search(r'[.!?]', name):
            return False

        if re.search(
            r'^(?:the|this|each|a|an|our|of|for|to)\b',
            name, re.I
        ):
            return False

        return True

    candidates = []

    # First search the first three pages for a title.
    for page_index in range(min(3, len(doc))):
        text_lines = [
            clean(line)
            for line in doc[page_index].get_text('text').splitlines()
            if clean(line)
        ]

        for index in range(len(text_lines)):
            # Join 1 to 5 consecutive lines to detect split titles.
            for count in range(1, 6):
                segment = text_lines[index:index + count]

                
                if len(segment) != count:
                    break

                # Do not merge standalone reporting dates
                # into fund titles on document covers.
                # Supports month-name dates and ISO dates.
                standalone_date = re.compile(
                    r'^(?:'
                    r'(?:January|February|March|April|May|June|'
                    r'July|August|September|October|November|December)'
                    r'\s+\d{1,2},?\s+20\d{2}'
                    r'|20\d{2}-\d{2}-\d{2}'
                    r')$',
                    re.I
                )

                if any(
                    standalone_date.fullmatch(line.strip())
                    for line in segment
                ):
                    continue

                name = clean(' '.join(segment))

                # Repair extracted text such as ETFPortfolio,
                # without inserting company-specific fund names.
                name = re.sub(
                    r'(?<=[A-Z])(?=[A-Z][a-z])',
                    ' ',
                    name
                )

                if not valid_name(name):
                    continue

                # Restrict multiline joins to title-like lines.
                if count > 1:
                    if not all(
                        len(line.split()) <= 7
                        and len(line) <= 65
                        for line in segment
                    ):
                        continue

                score = 100 - page_index * 25

                if index < 12:
                    score += 20

                if name.isupper():
                    score += 10

                # Prefer complete cover titles.
                if count > 1 and page_index == 0:
                    score += 5

                candidates.append(
                    (score, page_index, index, name)
                )

    # Metadata fallback, after removing report suffixes.
    metadata_title = clean(doc.metadata.get('title') or '')

    metadata_title = re.sub(
        r'(?<=[A-Z])(?=[A-Z][a-z])',
        ' ',
        metadata_title
    )

    metadata_title = re.sub(
        r'\s*[-–—:]\s*(?:MRFP|Management Report.*)$',
        '',
        metadata_title,
        flags=re.I
    ).strip()

    if valid_name(metadata_title):
        candidates.append(
            (85, 99, 0, metadata_title)
        )

    if not candidates:
        return None

    
    candidates.sort(
        key=lambda item: (-item[0], item[1], item[2])
    )

    selected_name = candidates[0][3]

    # Only compare names that differ in whitespace.
    # Do not allow unrelated fund names to influence selection.
    def name_identity(value):
        # Ignore whitespace differences only.
        # Preserve capitalization selected by the
        # existing fund-name scoring algorithm.
        return re.sub(r'\s+', '', value)


    selected_identity = name_identity(selected_name)

    # Count independent, complete line occurrences across
    # the document, rather than trusting the first PDF header.
    occurrences = {}

    for page_index in range(min(len(doc), 8)):
        page_lines = [
            clean(line)
            for line in doc[page_index].get_text('text').splitlines()
            if clean(line)
        ]

        seen_on_page = set()

        for line in page_lines:
            if not valid_name(line):
                continue

            if name_identity(line) != selected_identity:
                continue

            seen_on_page.add(line)

        for name in seen_on_page:
            occurrences[name] = occurrences.get(name, 0) + 1

    # Preserve the existing selection unless another
    # equivalent formatting has stronger page-level support.
    if occurrences:
        ranked = sorted(
            occurrences.items(),
            key=lambda item: (-item[1], item[0] != selected_name)
        )

        best_name, best_count = ranked[0]
        original_count = occurrences.get(selected_name, 0)

        if best_count >= 2 and best_count > original_count:
            selected_name = best_name

    return selected_name


MONTH_PATTERN = (
    r'January|February|March|April|May|June|July|'
    r'August|September|October|November|December|'
    r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec'
)

FULL_DATE = re.compile(
    rf'\b(?:{MONTH_PATTERN})\.?\s+\d{{1,2}},?\s+20\d{{2}}\b'
    r'|\b\d{1,2}/\d{1,2}/20\d{2}\b',
    re.I
)


def parse_report_date(value):
    """Convert supported PDF date formats to YYYY-MM-DD."""
    value = clean(value).replace(',', '')
    value = re.sub(r'\bSept\b', 'Sep', value, flags=re.I)
    value = re.sub(r'\b([A-Za-z]{3})\.', r'\1', value)

    formats = (
        '%B %d %Y',
        '%b %d %Y',
        '%m/%d/%Y'
    )

    for date_format in formats:
        try:
            return datetime.strptime(
                value, date_format
            ).date().isoformat()
        except ValueError:
            continue

    return None

def resolve_table_date(year, explicit_date=None, period_date=None):
    """
    Resolve a ratio-table reporting date safely.

    Priority:
    1. Explicit date associated with the table column/row.
    2. Document reporting date, only when the same year matches.
    3. Unknown date.

    Historical year-only columns remain unknown unless their
    actual month/day can be established.
    """
    if explicit_date:
        parsed = parse_report_date(explicit_date)

        if parsed and int(parsed[:4]) == year:
            return parsed

        return None

    if period_date and int(period_date[:4]) == year:
        return period_date

    return None

def detect_report_date(doc):
    """Find the latest explicitly labelled MRFP reporting date."""
    candidates = []

    reporting_context = re.compile(
        r'for\s+the\s+(?:year|six\s+months|period)\s+ended'
        r'|(?:annual|semi.annual)\s+management\s+report'
        r'|(?:series|class)\s+[A-Z0-9-]+\s*\(\s*as\s+at'
        r'|ETF\s+series\s*\(\s*as\s+at'
        r'|^as\s+at\b'
        r'|^ratios\s+and\s+supplemental\s+data',
        re.I
    )

    for page_number, page in enumerate(doc, start=1):
        lines = [
            clean(line)
            for line in page.get_text('text').splitlines()
            if clean(line)
        ]

        for index, line in enumerate(lines):
            # Join a heading and its immediately following date line.
            context = clean(' '.join(lines[max(0, index - 1):index + 1]))

            if not reporting_context.search(context):
                continue

            for match in FULL_DATE.finditer(context):
                parsed = parse_report_date(match.group())

                if parsed:
                    candidates.append({
                        'date': parsed,
                        'page': page_number,
                        'source': context[:180]
                    })

    if not candidates:
        return None

    # Historical dates can also appear in the same report.
    # Choose the latest date among explicitly labelled candidates.
    return max(item['date'] for item in candidates)



def table_date_candidates(page):
    """Find dates on visual rows with accurate word coordinates."""
    rows = lines(page_items(page))
    dates = []

    for index, row in enumerate(rows):
        words = row['words']

        if not words:
            continue

        # Build text and retain the character span of each PDF word.
        parts = []
        spans = []
        offset = 0

        for word in words:
            if parts:
                offset += 1

            start = offset
            parts.append(word.text)
            offset += len(word.text)
            spans.append((start, offset, word))

        text = ' '.join(parts)

        for match in FULL_DATE.finditer(text):
            parsed = parse_report_date(match.group())

            if not parsed:
                continue

            matched_words = [
                word
                for start, end, word in spans
                if start < match.end() and end > match.start()
            ]

            if not matched_words:
                continue

            x0 = min(w.x0 for w in matched_words)
            x1 = max(w.x1 for w in matched_words)
            y0 = min(w.y0 for w in matched_words)
            y1 = max(w.y1 for w in matched_words)

            dates.append({
                'date': parsed,
                'row': index,
                'x': round((x0 + x1) / 2, 1),
                'y': round((y0 + y1) / 2, 1),
                'x0': round(x0, 1),
                'x1': round(x1, 1),
                'text': text[:150]
            })

    return dates


def match_metric_to_column_date(
    metric_x, metric_y, date_candidates,
    max_vertical_distance=180,
    max_horizontal_distance=45
):
    """Associate a metric value with a dated column above it."""

    eligible = []

    for candidate in date_candidates:
        vertical_distance = metric_y - candidate['y']
        horizontal_distance = abs(metric_x - candidate['x'])

        # Column heading must be above the metric value.
        if not (0 <= vertical_distance <= max_vertical_distance):
            continue

        if horizontal_distance > max_horizontal_distance:
            continue

        eligible.append((
            vertical_distance,
            horizontal_distance,
            candidate
        ))

    if not eligible:
        return None

    # Nearest relevant header above the metric.
    eligible.sort(key=lambda item: (item[0], item[1]))

    return eligible[0][2]

def fragmented_table_dates(page):
    """
    Reconstruct dates spread across consecutive table-header rows.

    Example:
       June       December
       30         31
       2026(4)    2025

    Uses alignment and valid calendar dates, not fund names.
    """
    rows = lines(page_items(page))
    found = []

    months = re.compile(
        r'^(January|February|March|April|May|June|July|'
        r'August|September|October|November|December|'
        r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?$',
        re.I
    )

    days = re.compile(r'^\d{1,2}$')
    years = re.compile(
        r'^(20[0-3]\d)(?:\([a-z0-9]+\)|[*†‡]+)?$',
        re.I
    )

    for i in range(len(rows) - 2):
        month_row = rows[i]
        day_row = rows[i + 1]
        year_row = rows[i + 2]

        # Header components must be vertically close.
        if not (
            0 < day_row['y'] - month_row['y'] <= 25
            and 0 < year_row['y'] - day_row['y'] <= 25
        ):
            continue

        month_words = [
            w for w in month_row['words']
            if months.fullmatch(w.text)
        ]

        day_words = [
            w for w in day_row['words']
            if days.fullmatch(w.text)
            and 1 <= int(w.text) <= 31
        ]

        year_words = [
            (w, years.fullmatch(w.text))
            for w in year_row['words']
            if years.fullmatch(w.text)
        ]

        # Require at least two columns to identify a table header.
        if not (
            len(month_words) >= 2
            and len(day_words) >= 2
            and len(year_words) >= 2
        ):
            continue

        used_days = set()
        used_years = set()
        reconstructed = []

        for month_word in month_words:
            available_days = [
                (j, w) for j, w in enumerate(day_words)
                if j not in used_days
                and abs(w.cx - month_word.cx) <= 25
            ]

            if not available_days:
                continue

            day_index, day_word = min(
                available_days,
                key=lambda item: abs(item[1].cx - month_word.cx)
            )

            available_years = [
                (j, w, match)
                for j, (w, match) in enumerate(year_words)
                if j not in used_years
                and abs(w.cx - day_word.cx) <= 25
            ]

            if not available_years:
                continue

            year_index, year_word, year_match = min(
                available_years,
                key=lambda item: abs(item[1].cx - day_word.cx)
            )

            year = int(year_match.group(1))

            date_text = (
                month_word.text.rstrip('.')
                + ' ' + day_word.text
                + ' ' + str(year)
            )

            parsed = parse_report_date(date_text)

            if parsed is None:
                continue

            used_days.add(day_index)
            used_years.add(year_index)

            reconstructed.append({
                'date': parsed,
                'year': year,
                'x': round(
                    (month_word.cx + day_word.cx + year_word.cx) / 3,
                    1
                ),
                'header_row': i,
                'header_y': round(year_row['y'], 1),
                'source': date_text
            })

        # Reject incomplete or weakly aligned header groups.
        if len(reconstructed) < 2:
            continue

        class_match = CLASSES.search(day_row['text'])

        for item in reconstructed:
            item['class_name'] = (
                clean(class_match.group())
                if class_match else None
            )
            found.append(item)

    return found


def two_line_table_dates(page):
    """
    Detect table dates split across two nearby rows.

    Example:
        June 30,       December 31,
        2026  2025  2024  2023

    Only accepts month/day text aligned with a year column.
    """
    rows = lines(page_items(page))
    found = []

    month_day = re.compile(
        r'^(January|February|March|April|May|June|July|'
        r'August|September|October|November|December|'
        r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)'
        r'\.?\s+(\d{1,2}),?$',
        re.I
    )

    year_pattern = re.compile(
        r'^(20[0-3]\d)(?:\([a-z0-9]+\)|[*†‡]+)?$',
        re.I
    )

    for i in range(len(rows) - 1):
        upper = rows[i]
        lower = rows[i + 1]

        if not (0 < lower['y'] - upper['y'] <= 20):
            continue

        years = [
            w for w in lower['words']
            if year_pattern.fullmatch(w.text.strip())
        ]

        if len(years) < 2:
            continue

        # Avoid interpreting prose dates as table headers.
        if len(upper['words']) > 12:
            continue

        words = upper['words']

        for j in range(len(words) - 1):
            left = words[j]
            right = words[j + 1]

            text = clean(left.text + ' ' + right.text)
            match = month_day.fullmatch(text)

            if not match:
                continue

            center_x = (left.cx + right.cx) / 2

            nearest_year = min(
                years,
                key=lambda w: abs(w.cx - center_x)
            )

            if abs(nearest_year.cx - center_x) > 25:
                continue

            parsed = parse_report_date(
                f"{match.group(1)} {match.group(2)}, "
                f"{year_pattern.fullmatch(nearest_year.text.strip()).group(1)}"
            )

            if not parsed:
                continue

            found.append({
                'date': parsed,
                'year': int(parsed[:4]),
                'x': round(nearest_year.cx, 1),
                'header_y': round(lower['y'], 1),
                'header_row': i,
                'source': 'two-line-column',
                'class_name': None
            })

    return found


def spanning_table_dates(page):
    """
    Resolve date headers spanning multiple year columns.

    Supports structures such as:

      June 30,          December 31,
      2026 2025 2024 2023 2022 2021

    Requires an explicit explanatory note confirming
    the date of historical year columns.
    """
    rows = lines(page_items(page))
    results = []

    year_pattern = re.compile(
        r'^(20[0-3]\d)(?:\([a-z0-9]+\)|[*†‡]+)?$',
        re.I
    )

    for i in range(len(rows) - 1):
        header = rows[i]
        year_row = rows[i + 1]

        if not (0 < year_row['y'] - header['y'] <= 20):
            continue

        year_words = [
            w for w in year_row['words']
            if year_pattern.fullmatch(w.text.strip())
        ]

        if len(year_words) < 3:
            continue

        # Require a recognizable ratio table beneath the header.
        ratio_sections = [
            r for r in rows
            if year_row['y'] < r['y']
            and re.search(
                r'\bratios?\s+and\s+supplemental\s+data\b',
                r['text'], re.I
            )
        ]

        # A spanning header must identify one unambiguous
        # ratio section. Multiple sections require more
        # detailed table-to-header association.
        if len(ratio_sections) != 1:
            continue

        
        section_y = ratio_sections[0]['y']

        # Identify a new, unrelated financial section.
        # Do not borrow its footnotes for the ratio table.
        section_boundary = re.compile(
            r'^(?:Other Financial Information|'
            r'Investment Objective(?:s)?(?: and Strategies)?|'
            r'Results of Operations|'
            r'Past Performance|'
            r'Management Fees|'
            r'Summary of Investment Portfolio|'
            r'Financial Highlights)\s*$',
            re.I
        )

        later_sections = [
            r['y']
            for r in rows
            if r['y'] > section_y
            and section_boundary.fullmatch(r['text'].strip())
        ]

        section_end = (
            min(later_sections)
            if later_sections
            else float('inf')
        )

        # Accept date evidence only within this ratio section.
        notes = [
            r['text']
            for r in rows
            if section_y < r['y'] < section_end
            and re.search(
                r'\b(?:information|data|figures)\b',
                r['text'], re.I
            )
        ]

        note_text = ' '.join(notes)

        # Require an explicit statement that historical years
        # use December 31, not merely a visual assumption.
        confirmed = re.search(
            r'\bDecember\s+31\s+of\s+the\s+years\s+shown\b',
            note_text,
            re.I
        )

        if not confirmed:
            continue

        current = [
            w for w in year_words
            if int(year_pattern.fullmatch(
                w.text.strip()
            ).group(1)) == max(
                int(year_pattern.fullmatch(
                    z.text.strip()
                ).group(1))
                for z in year_words
            )
        ]

        if len(current) != 1:
            continue


        current_x = current[0].cx

        # Validate the historical spanning heading.
        # The heading must appear above the year columns,
        # on the historical side of the current-year column.
        header_words = header['words']

        month_positions = [
            w.cx for w in header_words
            if re.fullmatch(r'December|Dec\.?', w.text, re.I)
        ]

        day_positions = [
            w.cx for w in header_words
            if re.fullmatch(r'31,?', w.text)
        ]

        if not month_positions or not day_positions:
            continue

        historical_columns = [
            w for w in year_words
            if w.cx > current_x
        ]

        if len(historical_columns) < 2:
            continue

        heading_center = (
            month_positions[0] + day_positions[0]
        ) / 2

        historical_min = min(
            w.cx for w in historical_columns
        )

        historical_max = max(
            w.cx for w in historical_columns
        )

        # Require the spanning heading to be positioned
        # within the historical year-column region.
        if not (
            historical_min <= heading_center <= historical_max
        ):
            continue

        # The year columns must be ordered visually and
        # must not contain duplicate year labels.
        years = [
            int(year_pattern.fullmatch(
                w.text.strip()
            ).group(1))
            for w in year_words
        ]

        if len(years) != len(set(years)):
            continue

        # Reject weak evidence from widely separated headers.
        if year_row['y'] - header['y'] > 20:
            continue

        for word in year_words:

            year = int(
                year_pattern.fullmatch(
                    word.text.strip()
                ).group(1)
            )

            # Exclude the current interim year.
            if word.cx <= current_x:
                continue

            date_text = f"December 31, {year}"
            parsed = parse_report_date(date_text)

            if parsed is None:
                continue

            results.append({
                'date': parsed,
                'year': year,
                'x': round(word.cx, 1),
                'header_y': round(year_row['y'], 1),
                'header_row': i,
                'source': 'spanning-historical-header',
                'class_name': None
            })

    return results


def match_spanning_metric_date(
    metric,
    date_headers,
    page,
    max_horizontal_distance=25
):
    """
    Match a ratio candidate to a historical date column.

    Requires:
    - Exact reporting year
    - Matching horizontal position
    - One intervening ratio-section heading
    - Candidate before explanatory footnotes
    - No intervening unrelated section
    - Exactly one unambiguous date match
    """
    rows = lines(page_items(page))

    metric_x = metric['x']
    metric_y = metric['y']
    metric_year = metric['year']

    ratio_pattern = re.compile(
        r'\bratios?\s+and\s+supplemental\s+data\b',
        re.I
    )

    boundary_pattern = re.compile(
        r'^(?:Other Financial Information|'
        r'Investment Objective(?:s)?(?: and Strategies)?|'
        r'Results of Operations|'
        r'Past Performance|'
        r'Management Fees|'
        r'Summary of Investment Portfolio|'
        r'Financial Highlights)\s*$',
        re.I
    )

    matches = []

    for header in date_headers:
        if header['year'] != metric_year:
            continue

        if abs(header['x'] - metric_x) > max_horizontal_distance:
            continue

        if header['header_y'] >= metric_y:
            continue

        sections = [
            row for row in rows
            if header['header_y'] < row['y'] < metric_y
            and ratio_pattern.search(row['text'])
        ]

        if len(sections) != 1:
            continue

        section_y = sections[0]['y']

        # Reject metrics located in another document section.
        boundaries = [
            row for row in rows
            if section_y < row['y'] <= metric_y
            and boundary_pattern.fullmatch(
                row['text'].strip()
            )
        ]

        if boundaries:
            continue

        # Reject content after the first explanatory footnote.
        footnotes = [
            row for row in rows
            if section_y < row['y'] <= metric_y
            and re.match(
                r'^\s*\([a-z]\)\s+',
                row['text'],
                re.I
            )
        ]

        if footnotes:
            continue

        matches.append(header)

    if len(matches) != 1:
        return None

    return matches[0]



def match_two_line_metric_date(
    metric,
    date_headers,
    page,
    max_horizontal_distance=25
):
    """
    Match two-line table dates to ratio values.

    Safeguards:
    - Matching reporting year
    - Matching X column
    - Ratio-section heading required
    - Candidate must be above the explanatory footnotes
    - Ambiguous matches are rejected
    """
    rows = lines(page_items(page))

    metric_y = metric['y']
    metric_x = metric['x']
    metric_year = metric['year']

    ratio_headings = [
        row for row in rows
        if re.search(
            r'\bratios?\s+and\s+supplemental\s+data\b',
            row['text'],
            re.I
        )
    ]

    matches = []

    for header in date_headers:
        if header['year'] != metric_year:
            continue

        if header['header_y'] >= metric_y:
            continue

        if abs(header['x'] - metric_x) > max_horizontal_distance:
            continue

        # Locate the ratio section after this date header.
        sections = [
            row for row in ratio_headings
            if header['header_y'] < row['y'] < metric_y
        ]

        if len(sections) != 1:
            continue

        section = sections[0]

        # Metric must be reasonably below the section heading.
        if metric_y <= section['y']:
            continue

        # Detect the first explanatory footnote after the section.
        footnote_rows = [
            row for row in rows
            if row['y'] > section['y']
            and re.match(
                r'^\s*\([a-z]\)\s+',
                row['text'],
                re.I
            )
        ]

        if footnote_rows:
            footnote_start = min(
                row['y'] for row in footnote_rows
            )

            if metric_y >= footnote_start:
                continue

        # Reject if another ratio section exists between the
        # selected heading and the candidate.
        intervening_sections = [
            row for row in ratio_headings
            if section['y'] < row['y'] < metric_y
        ]

        if intervening_sections:
            continue

        matches.append(header)

    if len(matches) != 1:
        return None

    return matches[0]


def match_repeated_header_metric_date(
    metric,
    date_headers,
    page,
    max_horizontal_distance=25
):
    """
    Match dates for consecutive class tables with repeated
    month/day + year headers.

    Requires an enclosing ratio section, exact year, column
    alignment, and a unique date within the nearest header group.
    """
    rows = lines(page_items(page))
    metric_y = metric['y']
    metric_x = metric['x']
    metric_year = metric['year']

    ratio_pattern = re.compile(
        r'\bratios?\s+and\s+supplemental\s+data\b',
        re.I
    )

    ratio_sections = sorted(
        (r['y'] for r in rows if ratio_pattern.search(r['text']))
    )

    # Identify the nearest recognized date-header group
    # preceding this particular metric.
    preceding = [
        h for h in date_headers
        if h['header_y'] < metric_y
    ]

    if not preceding:
        return None

    nearest_y = max(h['header_y'] for h in preceding)

    # The header group must belong to a recognized ratio section.
    section_before_header = [
        y for y in ratio_sections
        if y < nearest_y
    ]

    
    if section_before_header:
        section_y = max(section_before_header)
    else:
        # A continuation page may omit the repeated
        # "Ratios and Supplemental Data" heading.
        #
        # Require local evidence of an actual ratio table.
        header_rows = [
            r for r in rows
            if abs(r['y'] - nearest_y) <= 1
        ]

        if not header_rows:
            return None

        preceding_rows = [
            r for r in rows
            if r['y'] < nearest_y
        ]

        # Require a class/series heading above the date header.
        class_heading = re.compile(
            r'^(?:Advisor\s+Series|'
            r'Series\s+[A-Z][A-Z0-9]*|'
            r'Class\s+[A-Z][A-Z0-9]*|'
            r'ETF\s+(?:Units|Series)|'
            r'Institutional\s+(?:Series|Class))$',
            re.I
        )

        headings = [
            r for r in preceding_rows
            if class_heading.fullmatch(r['text'].strip())
        ]

        if not headings:
            return None

        section_y = headings[-1]['y']

        # Require metric labels under the local date header.
        table_text = ' '.join(
            r['text']
            for r in rows
            if nearest_y < r['y'] <= metric_y + 60
        )

        required_patterns = (
            r'management\s+expense\s+ratio',
            r'trading\s+expense\s+ratio',
            r'portfolio\s+turnover\s+rate',
        )

        if not all(
            re.search(pattern, table_text, re.I)
            for pattern in required_patterns
        ):
            return None

    # Reject any intervening ratio-section heading.
    
    # Reject metrics located inside explanatory footnotes.
    # Footnotes may use numeric markers (1), (2), etc.,
    # or alphabetic markers (a), (b), etc.
    footnote_marker = re.compile(
        r'^\s*\((?:\d{1,2}|[a-z])\)\s+\S',
        re.I
    )

    footnote_starts = [
        r['y']
        for r in rows
        if nearest_y < r['y']
        and footnote_marker.match(r['text'])
    ]

    if footnote_starts:
        first_footnote_y = min(footnote_starts)

        if metric_y >= first_footnote_y:
            return None


    # Do not borrow dates from another header group.
    group = [
        h for h in preceding
        if abs(h['header_y'] - nearest_y) <= 1
    ]

    matches = [
        h for h in group
        if h['year'] == metric_year
        and abs(h['x'] - metric_x)
            <= max_horizontal_distance
    ]

    if len(matches) != 1:
        return None

    # Reject explanatory footnote regions.
    if any(
        section_y < r['y'] <= metric_y
        and re.match(r'^\s*\([a-z]\)\s+', r['text'], re.I)
        for r in rows
    ):
        return None

    return matches[0]




def match_fragmented_metric_date(
    metric, date_headers, max_horizontal_distance=25
):
    """
    Match a metric candidate to a reconstructed date column.

    Protects against matching values to another class's table.
    Does not modify extraction results.
    """
    metric_page_y = metric.get('y')
    metric_x = metric.get('x')
    metric_class = metric.get('class_name')

    if metric_page_y is None or metric_x is None:
        return None

    # Each reconstructed header belongs to one table.
    groups = {}

    for header in date_headers:
        key = header['header_row']
        groups.setdefault(key, []).append(header)

    if not groups:
        return None

    # Use only the closest preceding table header.
    eligible = [
        group
        for group in groups.values()
        if group[0]['header_y'] <= metric_page_y
    ]

    if not eligible:
        return None

    active_group = max(
        eligible,
        key=lambda group: group[0]['header_y']
    )

    header_class = active_group[0].get('class_name')

    if (
        header_class
        and metric_class
        and canonical(header_class) != canonical(metric_class)
    ):
        return None

    # Match the value to the closest date column.
    closest = min(
        active_group,
        key=lambda header: abs(header['x'] - metric_x)
    )

    if abs(closest['x'] - metric_x) > max_horizontal_distance:
        return None

    # Verify the metric candidate's year matches the column.
    if metric.get('year') != closest['year']:
        return None

    return closest


def match_metric_to_row_date(
    metric, date_candidates, max_vertical_distance=4
):
    """
    Associate a metric value with an explicit date
    on the same visual row.

    Requires a matching reporting year and page position.
    """
    metric_y = metric.get('y')
    metric_year = metric.get('year')

    if metric_y is None or metric_year is None:
        return None

    matches = [
        candidate
        for candidate in date_candidates
        if abs(candidate['y'] - metric_y) <= max_vertical_distance
        and int(candidate['date'][:4]) == metric_year
    ]

    # Do not guess when multiple dates are on the same row.
    unique_dates = {item['date'] for item in matches}

    if len(unique_dates) != 1:
        return None

    return min(
        matches,
        key=lambda item: abs(item['y'] - metric_y)
    )



def local_ratio_year_date_headers(page):
    """
    Detect year-only ratio columns supported by local
    reporting-date footnotes.

    Separates side-by-side tables geometrically.
    Rejects missing or ambiguous date evidence.
    """
    rows = lines(page_items(page))
    found = []

    year_re = re.compile(r'^(20[0-3]\d)$')
    month_re = (
        r'(January|February|March|April|May|June|'
        r'July|August|September|October|November|December)'
    )

    header_rows = [
        row for row in rows
        if sum(
            bool(year_re.fullmatch(w.text.strip()))
            for w in row['words']
        ) >= 3
    ]

    for header in header_rows:
        header_y = header['y']

        later_headers = [
            row['y']
            for row in header_rows
            if row['y'] > header_y + 1
        ]

        end_y = (
            min(later_headers)
            if later_headers else float('inf')
        )

        years = [
            w for w in header['words']
            if year_re.fullmatch(w.text.strip())
        ]

        groups = []
        current = []

        for word in years:
            if current and word.cx - current[-1].cx > 65:
                if len(current) >= 3:
                    groups.append(current)
                current = []
            current.append(word)

        if len(current) >= 3:
            groups.append(current)

        for group in groups:
            if len({w.text for w in group}) != len(group):
                continue

            group_x = [w.cx for w in group]
            first_x = min(group_x)
            last_x = max(group_x)

            # Find the PDF text block containing the
            # year-column header for this table.
            matching_blocks = []

            for block in page.get_text("blocks"):
                x0, y0, x1, y1, block_text, *_ = block

                if not (
                    x0 <= first_x <= x1
                    and x0 <= last_x <= x1
                    and y0 - 2 <= header_y <= y1 + 2
                ):
                    continue

                # Require this block to contain the exact
                # year sequence of the current column group.
                year_sequence = (
                    r'\b' +
                    r'\s+'.join(
                        re.escape(w.text)
                        for w in group
                    ) +
                    r'\b'
                )

                if not re.search(
                    year_sequence, block_text
                ):
                    continue

                matching_blocks.append(
                    (x0, y0, x1, y1)
                )

            # Ambiguous or unavailable block boundaries
            # must not produce inferred reporting dates.
            if len(matching_blocks) != 1:
                continue

            left_bound, _, right_bound, _ = (
                matching_blocks[0]
            )

            # Small allowance for PDF text positioning.
            left_bound -= 2
            right_bound += 2

            def region_text(row):
                return ' '.join(
                    w.text for w in row['words']
                    if left_bound <= w.cx <= right_bound
                )

            local_rows = [
                row for row in rows
                if header_y < row['y'] < end_y
            ]

            # Confirm MER, TER, and PTR labels inside
            # this table region.
            metric_text = ' '.join(
                region_text(row)
                for row in local_rows
                if row['y'] - header_y <= 160
            )

            required = (
                r'management\s+expense\s+ratio',
                r'trading\s+expense\s+ratio',
                r'portfolio\s+turnover\s+rate',
            )

            if not all(
                re.search(pattern, metric_text, re.I)
                for pattern in required
            ):
                continue

            # Find the local ratio-table note start.
            note_indices = [
                i for i, row in enumerate(local_rows)
                if re.search(
                    r'financial\s+information\s+presented\s+in'
                    r'\s+the\s+Ratios?\s+and\s+Supplemental'
                    r'\s+Data\s+table',
                    region_text(row), re.I
                )
            ]

            if len(note_indices) != 1:
                continue

            note_index = note_indices[0]

            note_text = ' '.join(
                region_text(row)
                for row in local_rows[
                    note_index:note_index + 4
                ]
            )

            default = re.search(
                rf'provided\s+as\s+at\s+{month_re}\s+'
                r'(\d{1,2})\s+of\s+the\s+year\s+shown',
                note_text, re.I
            )

            if not default:
                continue

            default_month = default.group(1)
            default_day = default.group(2)

            exception_pattern = re.compile(
                rf'except\s+(20[0-3]\d)'
                rf'(?:(?!\bexcept\s+20[0-3]\d\b).)*?'
                rf'(?:shown|provided)\s+as\s+at\s+'
                rf'{month_re}\s+(\d{{1,2}})',
                re.I | re.S
            )

            matches = list(
                exception_pattern.finditer(note_text)
            )

            exceptions = {
                (
                    int(m.group(1)),
                    m.group(2),
                    m.group(3)
                )
                for m in matches
            }

            mentioned_years = {
                int(y) for y in re.findall(
                    r'\bexcept\s+(20[0-3]\d)\b',
                    note_text, re.I
                )
            }

            # Every mentioned exception must resolve
            # to exactly one date.
            exception_by_year = {}

            for year in mentioned_years:
                values = {
                    (month, day)
                    for matched_year, month, day
                    in exceptions
                    if matched_year == year
                }

                if len(values) != 1:
                    break

                exception_by_year[year] = next(
                    iter(values)
                )

            if set(exception_by_year) != mentioned_years:
                continue

            for word in group:
                year = int(word.text)
                month, day = exception_by_year.get(
                    year,
                    (default_month, default_day)
                )

                parsed = parse_report_date(
                    f'{month} {day}, {year}'
                )

                if not parsed:
                    continue

                found.append({
                    'date': parsed,
                    'year': year,
                    'x': round(word.cx, 1),
                    'header_y': round(header_y, 1),
                    'source': 'local-ratio-year-note',
                })

    return found




def year_only_reporting_headers(page):
    """
    Find year-only ratio-table columns supported by an
    explicit reporting-period end date on the same page.

    Does not modify candidate metrics.
    """
    rows = lines(page_items(page))
    found = []

    year_re = re.compile(r'^(20[0-3]\d)$')
    date_re = re.compile(
        r'\b(?:January|February|March|April|May|June|'
        r'July|August|September|October|November|December)'
        r'\s+\d{1,2},?\s+20[0-3]\d\b',
        re.I
    )

    # Extract explicit date ranges and retain their positions.
    # A date must later be associated with a local table,
    # not automatically shared across the entire page.
    periods = {}
    period_positions = {}

    for row in rows:
        text = row['text']

        if not re.search(
            r'information presented is for the period',
            text, re.I
        ):
            continue

        for match in re.finditer(
            r'information presented is for the period'
            r'\s+(' + date_re.pattern + r')'
            r'\s+to\s+(' + date_re.pattern + r')',
            text, re.I
        ):
            end_date = parse_report_date(match.group(2))

            if end_date:
                year = int(end_date[:4])
                periods.setdefault(year, set()).add(end_date)
                period_positions.setdefault(
                    (year, end_date), []
                ).append(row['y'])


    # Reject conflicting reporting-period endpoints.
    periods = {
        year: next(iter(dates))
        for year, dates in periods.items()
        if len(dates) == 1
    }

    if not periods:
        return []

    for row in rows:
        years = [
            word for word in row['words']
            if year_re.fullmatch(word.text.strip())
        ]

        if len(years) < 3:
            continue

        groups = []
        current = []

        for word in years:
            if current and word.cx - current[-1].cx > 65:
                if len(current) >= 3:
                    groups.append(current)
                current = []
            current.append(word)

        if len(current) >= 3:
            groups.append(current)

        for group in groups:
            if len({w.text for w in group}) != len(group):
                continue

            # A candidate header must have ratio metric labels
            # reasonably below its vertical position.
            below = ' '.join(
                r['text']
                for r in rows
                if row['y'] < r['y'] <= row['y'] + 150
            )

            if not all(
                re.search(pattern, below, re.I)
                for pattern in (
                    r'management\s+expense\s+ratio',
                    r'trading\s+expense\s+ratio',
                    r'portfolio\s+turnover\s+rate',
                )
            ):
                continue

            
            for word in group:
                year = int(word.text)

                if year not in periods:
                    continue

                date = periods[year]

                # Use only reporting-period evidence that
                # appears after this table's year header.
                note_positions = [
                    y for y in period_positions.get(
                        (year, date), []
                    )
                    if y > row['y']
                ]

                if not note_positions:
                    continue

                note_y = min(note_positions)

                # Prevent borrowing a period note past a
                # separate intervening year-header table.
                intervening_headers = [
                    other['y']
                    for other in rows
                    if row['y'] < other['y'] < note_y
                    and other is not row
                    and len([
                        w for w in other['words']
                        if year_re.fullmatch(w.text.strip())
                    ]) >= 3
                ]

                if intervening_headers:
                    continue

                found.append({

                    'year': year,
                    'date': periods[year],
                    'x': round(word.cx, 1),
                    'header_y': round(row['y'], 1),
                    'source': 'year-only-period-note',
                })

    return found


def match_year_only_reporting_date(
    metric,
    headers,
    page,
    max_horizontal_distance=12
):
    """
    Match a metric to the closest preceding year-only
    header, with exact year and column alignment.
    """
    metric_x = metric['x']
    metric_y = metric['y']
    metric_year = metric['year']

    eligible = [
        header for header in headers
        if header['year'] == metric_year
        and header['header_y'] < metric_y
        and metric_y - header['header_y'] <= 160
        and abs(header['x'] - metric_x)
            <= max_horizontal_distance
    ]

    if not eligible:
        return None

    nearest_y = max(h['header_y'] for h in eligible)

    matches = [
        h for h in eligible
        if abs(h['header_y'] - nearest_y) <= 1
    ]

    if len(matches) != 1:
        return None

    # Reject metrics inside explanatory footnotes.
    rows = lines(page_items(page))

    footnote_re = re.compile(
        r'^\s*(?:\(\d{1,2}\)|\d{1,2}\))\s+\S'
    )

    footnotes = [
        r['y'] for r in rows
        if nearest_y < r['y'] <= metric_y
        and footnote_re.match(r['text'])
    ]

    if footnotes:
        return None

    return matches[0]


def annual_current_year_ratio_dates(page):
    """
    Detect current-year annual reporting dates where:
    - An explicit annual date appears on the page.
    - A multi-year ratio table exists.
    - Its footnote confirms December 31 for the years shown.
    - The current-year column is uniquely identifiable.

    Does not infer interim reporting dates.
    """
    rows = lines(page_items(page))
    results = []

    annual_pattern = re.compile(
        r'\bfor\s+the\s+year\s+ended\s+'
        r'(December\s+31,?\s+(20\d{2}))\b',
        re.I
    )

    annual_dates = []

    for row in rows:
        match = annual_pattern.search(row['text'])
        if not match:
            continue

        parsed = parse_report_date(match.group(1))
        if parsed:
            annual_dates.append((int(match.group(2)), parsed))

    if len(annual_dates) != 1:
        return []

    annual_year, annual_date = annual_dates[0]

    ratio_sections = [
        r for r in rows
        if re.search(
            r'\bratios?\s+and\s+supplemental\s+data\b',
            r['text'],
            re.I
        )
    ]

    if len(ratio_sections) != 1:
        return []

    
    section_y = ratio_sections[0]['y']

    # Stop at the next unrelated document section.
    # A reporting-date footnote beyond this boundary
    # must not be borrowed by the ratio table.
    boundary_pattern = re.compile(
        r'^(?:Other Financial Information|'
        r'Investment Objective(?:s)?(?: and Strategies)?|'
        r'Results of Operations|'
        r'Past Performance|'
        r'Management Fees|'
        r'Summary of Investment Portfolio|'
        r'Financial Highlights)\s*$',
        re.I
    )

    later_sections = [
        r['y']
        for r in rows
        if r['y'] > section_y
        and boundary_pattern.fullmatch(r['text'].strip())
    ]

    section_end = (
        min(later_sections)
        if later_sections
        else float('inf')
    )

    # Only accept reporting-date evidence inside
    # the same Ratios and Supplemental Data section.
    notes = [
        r for r in rows
        if section_y < r['y'] < section_end
        and re.search(
            r'\bthis\s+information\s+is\s+provided\s+'
            r'as\s+at\s+December\s+31\s+of\s+the\s+'
            r'years\s+shown\b',
            r['text'],
            re.I
        )
    ]


    if len(notes) != 1:
        return []

    note_y = notes[0]['y']

    year_pattern = re.compile(r'^20[0-3]\d$')
    candidates = []

    for row in rows:
        if row['y'] >= section_y:
            continue

        year_words = [
            w for w in row['words']
            if year_pattern.fullmatch(w.text.strip())
        ]

        if len(year_words) < 3:
            continue

        years = [int(w.text) for w in year_words]

        if len(years) != len(set(years)):
            continue

        if max(years) != annual_year:
            continue

        current_words = [
            w for w in year_words
            if int(w.text) == annual_year
        ]

        if len(current_words) != 1:
            continue

        current = current_words[0]

        # Current year should be the leftmost year column.
        if current.cx != min(w.cx for w in year_words):
            continue

        candidates.append((row, current))

    # Reject ambiguous or multiple matching year headers.
    if len(candidates) != 1:
        return []

    year_row, current = candidates[0]

    if not (year_row['y'] < section_y < note_y):
        return []

    results.append({
        'date': annual_date,
        'year': annual_year,
        'x': round(current.cx, 1),
        'header_y': round(year_row['y'], 1),
        'source': 'annual-current-year',
        'class_name': None
    })

    return results


def annotate_candidate_dates(page, candidates):
    """
    Attach evidence-backed dates to extracted metric candidates.

    Supports:
    - Explicit dates on metric rows
    - Fragmented month/day/year column headers
    - Explicit full-date column headers

    Does not alter MER/TER/PTR values.
    """
    explicit_dates = table_date_candidates(page)
    fragmented_dates = fragmented_table_dates(page)
    two_line_dates = two_line_table_dates(page)
    spanning_dates = spanning_table_dates(page)
    local_ratio_dates = local_ratio_year_date_headers(page)
    annual_current_dates = annual_current_year_ratio_dates(page)

    annotated = []


    for candidate in candidates:
        record = candidate.copy()
        record['report_date'] = None
        record['date_source'] = None

        # 1. Explicit date on the same row.
        match = match_metric_to_row_date(
            record, explicit_dates
        )

        if match:
            record['report_date'] = match['date']
            record['date_source'] = 'same-row'

        # 2. Fragmented column-header date.
        if record['report_date'] is None:
            match = match_fragmented_metric_date(
                record, fragmented_dates
            )

            if match:
                record['report_date'] = match['date']
                record['date_source'] = 'fragmented-column'
                
        # Match validated two-line date headers to ratio
        # candidates in the same table region.
        if record['report_date'] is None:
            match = match_two_line_metric_date(
                record,
                two_line_dates,
                page
            )

            if match:
                record['report_date'] = match['date']
                record['date_source'] = 'two-line-column'
                
        # 3. Repeated month/day + year headers.
        # Supports multi-class tables and continuation pages.
        # Only fills missing dates; never overwrites
        # higher-priority date evidence.
        if record['report_date'] is None:
            match = match_repeated_header_metric_date(
                record,
                two_line_dates,
                page
            )

            if match:
                record['report_date'] = match['date']
                record['date_source'] = 'repeated-header-column'

        
        # 4. Spanning historical date columns.
        # Preserve historical reporting dates where supported
        # by validated date-header evidence.
        # Never overwrite higher-priority matches.
        if record['report_date'] is None:
            match = match_spanning_metric_date(
                record,
                spanning_dates,
                page
            )

            if match:
                record['report_date'] = match['date']
                record['date_source'] = (
                    'spanning-historical-column'
                )

        # 5. Explicit complete-date column header.
        if record['report_date'] is None:
            headers = [

                d for d in explicit_dates
                if re.search(
                    r'ratios?\s+and\s+supplement',
                    d['text'],
                    re.I
                )
            ]

            match = match_metric_to_column_date(
                record['x'],
                record['y'],
                headers
            )

            if (
                match
                and int(match['date'][:4]) == record['year']
            ):
                record['report_date'] = match['date']
                record['date_source'] = 'explicit-column'

                
        # Year-only ratio-table dates supported by local,
        # explicitly labeled reporting-date footnotes.
        # Fallback only: preserve all existing date evidence.
        if record['report_date'] is None:
            match = match_year_only_reporting_date(
                record,
                local_ratio_dates,
                page
            )

            if match:
                record['report_date'] = match['date']
                record['date_source'] = 'local-ratio-year-note'


        # Explicit annual date for a current-year column.
        # Reuses ratio-section and footnote safeguards.
        # Never overwrites an existing reporting date.
        if record['report_date'] is None:
            match = match_spanning_metric_date(
                record,
                annual_current_dates,
                page
            )

            if match:
                record['report_date'] = match['date']
                record['date_source'] = 'annual-current-year'

        annotated.append(record)

    return annotated


def analyze(pdf_bytes,progress=None,enable_ocr=True):
 doc=pymupdf.open(stream=pdf_bytes,filetype='pdf')

 records=[]
 diagnostics=[]

 # Automatically detect the full fund name.
 detected_fund=detect_fund_name(doc)
 fund=detected_fund or 'Fund'

 for ix,page in enumerate(doc):
  n=ix+1

  if progress:
   progress(n,len(doc),'Reading native text')

  p_records,has_text=extract_native(page,n,fund)
  mode='native'

  # Only OCR if little/no native text.
  # Readable PDFs with unfamiliar tables need layout improvements,
  # not unnecessary OCR processing.
  if enable_ocr and (not has_text or len(page.get_text().strip())<40):
   mode='ocr'

   try:
    words=ocr_items(page)

    # OCR-backed page proxy using the existing extraction logic.
    class Proxy:
     rect=page.rect

     def get_text(self,what):
      if what=='words':
       return [
        (w.x0,w.y0,w.x1,w.y1,w.text,0,0,0)
        for w in words
       ]
      return ' '.join(w.text for w in words)

    p_records,_=extract_native(Proxy(),n,fund)

    for r in p_records:
     r['method']='ocr'

   except Exception as exc:
    LOG.exception('OCR failed on page %d',n)
    mode='ocr-failed: '+str(exc)[:100]

    
  # Attach evidence-backed dates before selecting results.
  # Keep OCR candidates undated for now unless their
  # reconstructed date coordinates have been validated.
  if mode == 'native':
   p_records=annotate_candidate_dates(page,p_records)
  else:
   for record in p_records:
    record['report_date']=None
    record['date_source']=None

  records.extend(p_records)

  diagnostics.append({
   'page':n,
   'mode':mode,
   'candidates':len(p_records)
  })

  if progress:
   progress(
    n,
    len(doc),
    'Extracted '+str(len(p_records))+' candidates'
   )

 # Keep existing MER/TER/PTR selection and PDF ordering.
 selected=select(records)

 # Add the detected fund name without changing class names.
 for row in selected:
  row['fund_name']=detected_fund

 doc.close()

 return selected,diagnostics,records




def select(records):
    """
    Select each class's latest available reporting period.

    Rules:
    - Prefer reliable full dates within each class.
    - Fall back to latest year when a class has no dated records.
    - Do not mix metrics across reporting periods.
    - Preserve MER priority.
    - Preserve class discovery order.
    """
    if not records:
        return []

    # Group candidates by class while preserving discovery order.
    groups = {}

    for record in records:
        key = canonical(record['class_name'])
        groups.setdefault(key, []).append(record)

    results = []

    for class_key, candidates in groups.items():
        dated = [
            r for r in candidates
            if r.get('report_date')
            and r['report_date'][:4] == str(r['year'])
        ]

        
        latest_known_year = max(
            r['year'] for r in candidates
        )

        latest_dated_year = max(
            (r['year'] for r in dated),
            default=None
        )

        needs_review = False

        if (
            dated
            and latest_dated_year >= latest_known_year
        ):
            latest_date = max(
                r['report_date'] for r in dated
            )

            eligible = [
                r for r in dated
                if r['report_date'] == latest_date
            ]

            latest_year = int(latest_date[:4])

            # A same-year candidate without a complete date
            # could belong to a different reporting period.
            needs_review = any(
                r['year'] == latest_year
                and not r.get('report_date')
                for r in candidates
            )

        else:
            latest_date = None
            latest_year = latest_known_year

            eligible = [
                r for r in candidates
                if r['year'] == latest_year
                and not r.get('report_date')
            ]

            needs_review = bool(dated)

        chosen = {}
        for record in eligible:
            metric = record['metric']
            previous = chosen.get(metric)

            if (
                previous is None
                or (record['priority'], record['page']) <
                   (previous['priority'], previous['page'])
            ):
                chosen[metric] = record

        row = {
            'class_name': candidates[0]['class_name'],
            'year': latest_year,
            'report_date': latest_date,
            'needs_review': needs_review,
            'MER': None,
            'TER': None,
            'PTR': None,
            'evidence': {},
        }

        for metric, record in chosen.items():
            row[metric] = record['value']

            row['evidence'][metric] = {
                'page': record['page'],
                'source': record['source'],
                'method': record['method'],
                'position': [record['x'], record['y']],
                'report_date': record.get('report_date'),
                'date_source': record.get('date_source')
            }

        results.append(row)

    return results

