"""Evidence-backed physical fund boundaries with page and vertical positions.

An issuer name in holdings/market commentary is never enough to start a fund.
Separate validated titles are required. False positives favor review, not mixing.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
import pymupdf

@dataclass(frozen=True)
class FundSection:
    name: str
    start_page: int                 # zero indexed
    start_y: float
    end_page: int                   # zero indexed, inclusive
    end_y: float
    source_page: int                # one indexed


def _normalized(text):
    return re.sub(r'\s+',' ',text or '').strip().casefold()


def find_sections(doc, primary_name, issuer, heading_regex=None):
    """Conservative detection. Repeated headers don't create new sections.

    Only a standalone fund title with a nearby main-section heading is accepted.
    If the report has only one validated fund, return the entire PDF as one region.
    """
    if not doc:
        return []
    if not heading_regex:
        return [FundSection(primary_name,0,0.0,len(doc)-1,doc[-1].rect.height,1)]
    candidates=[]
    pattern=re.compile(heading_regex,re.I)
    for pi,page in enumerate(doc):
        blocks=[]
        try:
            data=page.get_text('dict')
            for block in data.get('blocks',[]):
                for line in block.get('lines',[]):
                    spans=line.get('spans',[])
                    s=' '.join(x.get('text','') for x in spans).strip()
                    if not s or not pattern.fullmatch(s):
                        continue
                    y=float(line['bbox'][1]); size=max((x.get('size',0) for x in spans),default=0)
                    blocks.append((s,y,size))
        except Exception:
            continue
        for s,y,sz in blocks:
            # Require structural corroboration directly after a heading.
            next_text=page.get_text('text',clip=pymupdf.Rect(0,y+1,page.rect.width,min(page.rect.height,y+250)))
            if not re.search(r'Management Discussion of Fund Performance|Financial Highlights|Management Report of Fund Performance|Investment Objective',next_text,re.I):
                continue
            # In holdings lists, name mentions are rarely standalone large titles.
            if sz<9:
                continue
            if candidates and _normalized(candidates[-1][0]) == _normalized(s):
                continue
            candidates.append((s,pi,y))
    # One-fund PDFs often repeat their current title. Don't accidentally invent
    # a section on every page or on the title of an underlying investment.
    names={_normalized(s) for s,_,_ in candidates}
    if len(names)<2:
        return [FundSection(primary_name,0,0.0,len(doc)-1,doc[-1].rect.height,1)]
    # Group page ranges only once per novel named heading, in reading order.
    found=[]; used=set()
    for name,pi,y in candidates:
        k=_normalized(name)
        if k in used:
            continue
        used.add(k)
        found.append((name,pi,y))
    if len(found)<2:
        return [FundSection(primary_name,0,0.0,len(doc)-1,doc[-1].rect.height,1)]
    sections=[]
    for idx,(name,pi,y) in enumerate(found):
        if idx+1<len(found):
            _,ep,ey=found[idx+1]
            end_y=ey if ep==pi else doc[ep].rect.height if ep<pi else ey
            end_page=ep
        else:
            end_page=len(doc)-1;end_y=doc[-1].rect.height
        sections.append(FundSection(name,pi,y,end_page,end_y,pi+1))
    return sections


def extract_section_pdf(doc,section):
    """Create a PDF preserving text for a page-coordinate section.

    Skips other fund sections on shared pages. Output page numbers are remapped
    to source pages by the router after extracting evidence.
    """
    out=pymupdf.open(); source_pages=[]
    for pi in range(section.start_page,section.end_page+1):
        p=doc[pi]; y0=section.start_y if pi==section.start_page else 0
        y1=section.end_y if pi==section.end_page else p.rect.height
        if y1<=y0+2:
            continue
        rect=pymupdf.Rect(0,y0,p.rect.width,y1)
        q=out.new_page(width=p.rect.width,height=y1-y0)
        q.show_pdf_page(q.rect,doc,pi,clip=rect)
        source_pages.append(pi+1)
    try:
        return out.tobytes(),source_pages
    finally:
        out.close()
