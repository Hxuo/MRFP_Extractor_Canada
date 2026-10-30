"""Base contract for independent FMC extraction profiles."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,re
from mer import extractor as legacy
from mer.shared import table_stream
from mer.shared.fund_sections import find_sections, extract_section_pdf


def slug(s):
    return re.sub(r'[^a-z0-9]+','-',str(s or '').lower()).strip('-')


@dataclass
class FMCProfile:
    key: str
    label: str
    signature: tuple[str,...]
    negative: tuple[str,...]=()
    title_re: str | None=None
    class_style: str | None=None
    section_re: str | None=None

    def score(self,head):
        score=0
        for i,signature in enumerate(self.signature):
            if re.search(signature,head,re.I):
                score+=5 if i==0 else 2
        for pattern in self.negative:
            if re.search(pattern,head,re.I):
                score-=5
        return score

    def fund_name(self,doc):
        if self.title_re:
            pattern=re.compile(self.title_re,re.I|re.M)
            for page in list(doc)[:5]:
                m=pattern.search(page.get_text('text'))
                if m:
                    return re.sub(r'\s+',' ',m.group(1)).strip()
        return legacy.detect_fund_name(doc)

    def extract(self,doc,pdf_bytes,progress=None,enable_ocr=True):
        fund=self.fund_name(doc)
        if self.class_style:
            reporting_date=table_stream.parse_period(' '.join(p.get_text('text')[:1700] for p in list(doc)[:2]))
            # Some files have the fiscal-date confirmation after the title page.
            if not reporting_date:
                reporting_date=table_stream.parse_period(' '.join(p.get_text('text')[:3000] for p in list(doc)[:4]))
            rows,diag=table_stream.extract(doc,self.class_style,reporting_date)
            if rows:
                for row in rows:row['fund_name']=fund
                return rows,diag,[]
        # Built-in native extractor remains the fallback for validated layouts.
        rows,diag,raw=legacy.analyze(pdf_bytes,progress,enable_ocr)
        for row in rows:
            if fund:
                row['fund_name']=fund
        return rows,diag,raw


def stabilize_rows(rows,profile,source_page_map=None):
    """Stable identity to prevent same Series A in two different funds colliding."""
    for r in rows:
        fund=str(r.get('fund_name') or '').strip()
        cname=str(r.get('class_name') or '').strip()
        if not fund or not cname:
            r['needs_review']=True
        fid=hashlib.sha256((profile.key+'\x00'+fund.casefold()).encode()).hexdigest()[:20]
        cid=hashlib.sha256((fid+'\x00'+cname.casefold()).encode()).hexdigest()[:20]
        r['fmc']=profile.label
        r['fmc_key']=profile.key
        r['fund_id']=fid
        r['class_id']=cid
        r['row_id']=cid+':'+str(r.get('report_date') or r.get('year') or 'unknown')
        if source_page_map:
            for evidence in (r.get('evidence') or {}).values():
                n=evidence.get('page')
                if isinstance(n,int) and 1<=n<=len(source_page_map):
                    evidence['page']=source_page_map[n-1]
    return rows
