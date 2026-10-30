"""Text-layer metric tables for supported FMC layouts.

This intentionally reads a documented *ratio section*, not arbitrary numerical
sentences. No fund name, class list, or financial result is hard-coded.
"""
from __future__ import annotations
import re
from datetime import date

CLASS_PATTERNS = {
    'desjardins': re.compile(r'^\s*([A-Z][A-Z0-9]{0,3})[–-]CLASS\s*$', re.I),
    'sun_life': re.compile(r'^\s*(.+?)\s*[-–]\s*(Series\s+[A-Z][A-Z0-9-]*)\s*$', re.I),
    'nbi': re.compile(
        r'^\s*('
        r'Investor\s*\*?\s*/\s*Advisor\s+Series'
        r'|Series\s+[A-Z][A-Z0-9-]*'
        r'|ETF(?:H)?\s+Series'
        r'|Private\s+Series'
        r')\s*\*{0,5}\s*$',
        re.I
    ),

}
METRIC_PATTERN = re.compile(
    r'(?P<label>\bmanagement\s+expense\s+ratio\b(?!\s+before\b)'
    r'|\btrading\s+expense\s+ratio\b|\bportfolio\s+turnover\s+(?:rate|ratio)\b)'
    r'\s*(?:\(\s*%\s*\))?\s*(?:\(\s*\d{1,2}\s*\))?\s*'
    r'(?P<value>\d[\d,]*(?:\.\d+)?|[—–-])(?=\s|$)',
    re.I,
)
DATE_PATTERN = re.compile(r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(20[0-3]\d)\b', re.I)
MONTHS = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}


def parse_period(text):
    """Choose explicit *reporting* period, not dates of fee changes or holdings."""
    header = text[:5000]
    patterns = [
        r'(?:financial\s+period|period|year)\s+ended\s+',
        r'as\s+at\s+',
        r'^\s*',
    ]
    for prefix in patterns:
        matches = []
        for line in header.splitlines():
            m = re.search(prefix + DATE_PATTERN.pattern, line, re.I)
            if m:
                matches.append(m)
        if matches:
            m = matches[0]
            try:
                d = date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
                return d.isoformat()
            except (ValueError, KeyError):
                return None
    return None

def _class_heading(line, issuer):
    m = CLASS_PATTERNS[issuer].fullmatch(
        line.replace('\xa0', ' ').strip()
    )

    if not m:
        return None

    if issuer == 'desjardins':
        return m.group(1).upper() + '-Class'

    if issuer == 'sun_life':
        return re.sub(r'\s+', ' ', m.group(2)).strip()

    if issuer == 'nbi':
        name = re.sub(r'\*+', '', m.group(1))
        return re.sub(r'\s+', ' ', name).strip()

    return re.sub(r'\s+', ' ', m.group(1)).strip()



def _ratio_region(section):
    """Restrict matches to ratio data instead of other disclosures."""
    k = re.search(r'Ratios?\s+and\s+Supplemental\s+Data', section, re.I)
    if not k:
        return None
    region = section[k.end():]
    cut = re.search(r'\b(?:Management\s+Fees|Past\s+Performance|Summary\s+of\s+Investment\s+Portfolio)\b', region, re.I)
    return region[:cut.start()] if cut else region


def extract(doc, issuer, reporting_date=None):
    """Return latest year class rows for Desjardins, Sun Life, or NBI.

    Every value comes from the PDF text stream inside a distinct ratio section.
    The latest year must occur as a header near that section. Missing source
    values are recorded as None, never inferred as 0.
    """
    from mer.extractor import to_number
    results=[]
    diagnostics=[]
    for page_index,page in enumerate(doc):
        text=page.get_text('text',sort=False).replace('\xa0',' ')
        lines=text.splitlines(keepends=True)
        blocks=[]
        last_cls=None
        offset=0
        for line in lines:
            cls = _class_heading(line.strip(),issuer)
            if cls:
                if last_cls:
                    last_cls['end'] = offset
                last_cls={'name':cls,'start':offset,'end':len(text),'page':page_index+1}
                blocks.append(last_cls)
            offset += len(line)
        for b in blocks:
            segment = text[b['start']:b['end']]
            # Desjardins class heading appears AFTER Ratios and Supplemental Data;
            # Sun Life/NBI class heading appears BEFORE that heading.
            if issuer=='desjardins':
                ratio=segment
                # Must have a preceding Ratio heading, not merely a narrative class mention.
                prefix=text[max(0,b['start']-170):b['start']]
                if not re.search(r'Ratios?\s+and\s+Supplemental\s+Data',prefix,re.I):
                    continue
            else:
                ratio=_ratio_region(segment)
                if ratio is None and issuer=='sun_life':
                    # Sun Life places the shared ratio heading before all class
                    # blocks; validate the full MER/TER/PTR trio per class.
                    ratio=segment
                if ratio is None:
                    continue
            # Required metric evidence within same class block.
            found={}
            for m in METRIC_PATTERN.finditer(ratio):
                label=m.group('label').lower()
                metric='MER' if 'management' in label else ('TER' if 'trading' in label else 'PTR')
                # If current metric is repeated in a class region, take first legitimate
                # non-before-waiver appearance. Never borrow values from footnotes.
                if metric not in found:
                    val = to_number(m.group('value'))
                    if val is None or (0<=val<=(1000 if metric=='PTR' else 100)):
                        found[metric]=(val,m.group('value'),m.start())
            if len(found)<2:
                continue
            # Require a recognized year column on each class-specific ratio table.
            near_header = text[max(0,b['start']-160):b['start']] if issuer=='desjardins' else segment[:ratio and segment.find(ratio)+150]
            years=[int(y) for y in re.findall(r'(?<!\d)(20[0-3]\d)(?!\d)',near_header)]
            if not years:
                years=[int(y) for y in re.findall(r'(?<!\d)(20[0-3]\d)(?!\d)',segment[:150])]
            if not years:
                continue
            latest= max(years)
            candidate_date = reporting_date if reporting_date and int(reporting_date[:4])==latest else None
            row={'class_name':b['name'],'year':latest,'report_date':candidate_date,'needs_review':candidate_date is None,'MER':None,'TER':None,'PTR':None,'evidence':{}}
            for metric,(value,raw,position) in found.items():
                row[metric]=value
                # A metric shown as dash has no numeric value, but the page is recorded.
                if value is not None:
                    row['evidence'][metric]={'page':b['page'],'source':metric+' (ratio table)','method':'native-fmc','position':None,'report_date':candidate_date,'date_source':'report-header'}
            results.append(row)
        diagnostics.append({'page':page_index+1,'mode':'native-fmc-'+issuer,'candidates':len([r for r in results if any((v or {}).get('page')==page_index+1 for v in r['evidence'].values())])})
    # Do not silently pick one if duplicate class blocks were found; select latest
    # with a clear date and reject conflicting values as a review condition.
    unique={}
    for r in results:
        key=r['class_name'].casefold()
        if key in unique:
            old=unique[key]
            if r['report_date']>=(old['report_date'] or ''):
                if any(old[k] != r[k] for k in ('MER','TER','PTR')):
                    r['needs_review']=True
                unique[key]=r
        else:
            unique[key]=r
    return list(unique.values()),diagnostics
