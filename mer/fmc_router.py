"""FMC detection and trusted dispatch. Neither names nor values are hard-coded."""
from __future__ import annotations
import pymupdf
from mer.fmc import REGISTRY
from mer.fmc.base import stabilize_rows
from mer.shared.fund_sections import find_sections,extract_section_pdf
from mer import extractor as legacy


def detect_fmc(doc):
    # First/second page signatures are weighted to avoid detecting investment
    # holdings instead of the organization publishing the MRFP.
    head='\n'.join(doc[i].get_text('text') for i in range(min(len(doc),3)))
    scored=sorted(((p.score(head),p) for p in REGISTRY),key=lambda t:t[0],reverse=True)
    score,profile=scored[0]
    if score<5 or (len(scored)>1 and score==scored[1][0]):
        return None,{'status':'unknown_or_ambiguous','candidates':[(p.key,s) for s,p in scored[:3]]}
    return profile,{'status':'matched','fmc_key':profile.key,'score':score}


def analyze(pdf_bytes,progress=None,enable_ocr=True):
    with pymupdf.open(stream=pdf_bytes,filetype='pdf') as doc:
        profile,decision=detect_fmc(doc)
        if profile is None:
            rows,diag,raw=legacy.analyze(pdf_bytes,progress,enable_ocr)
            for row in rows:
                row['needs_review']=True
                row['fmc']='Unknown / Unsupported'
                row['fmc_key']='unknown'
                # Unknown layouts must never silently receive a verified state.
            return rows,[{'fmc_detection':decision,'warning':'Unrecognized FMC: tentative native extraction requires manual review'}]+diag,raw

        name=profile.fund_name(doc)
        sections=find_sections(doc,name,profile.key,profile.section_re)
        all_rows=[]; all_raw=[]; all_diag=[]
        multi=len(sections)>1
        for sec in sections:
            # When a PDF has multiple validated fund sections, isolate each
            # fund's region BEFORE extracting any class/metric evidence.
            if multi:
                section_pdf,page_map=extract_section_pdf(doc,sec)
                with pymupdf.open(stream=section_pdf,filetype='pdf') as subdoc:
                    rows,diag,raw=profile.extract(subdoc,section_pdf,progress,enable_ocr)
                for r in rows:r['fund_name']=sec.name
            else:
                page_map=None
                rows,diag,raw=profile.extract(doc,pdf_bytes,progress,enable_ocr)
            stabilize_rows(rows,profile,page_map)
            for d in diag:
                if page_map and isinstance(d,dict) and isinstance(d.get('page'),int) and 1<=d['page']<=len(page_map):
                    d['page']=page_map[d['page']-1]
            all_rows.extend(rows);all_diag.extend(diag);all_raw.extend(raw)
        # Reject duplicate identity/period combinations instead of silently
        # dropping a fund's Series A from a second section.
        by_id={}
        for row in all_rows:
            key=row['row_id']
            if key in by_id:
                row['needs_review']=True
                by_id[key]['needs_review']=True
                row['duplicate_identity']=True
            else:
                by_id[key]=row
        info={'fmc_detection':decision,'fund_sections':[{'name':s.name,'start_page':s.start_page+1,'end_page':s.end_page+1,'start_y':round(s.start_y,1),'end_y':round(s.end_y,1)} for s in sections]}
        return all_rows,[info]+all_diag,all_raw
