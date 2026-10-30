"""Reference-data acceptance tests for 12 supplied MRFPs (native PDF layer).

Values are transcribed from source ratio tables. If a new extraction disagrees,
inspect the PDF before changing either extraction logic or expected results.
"""
from pathlib import Path
import pytest
from mer.fmc_router import analyze,detect_fmc
import pymupdf

FIXTURES=Path(__file__).parent/'fixtures'
DATA={
'02103_rad_en.pdf': ('desjardins','Desjardins Active Strategy Balanced Portfolio','2025-09-30',{
 'A-Class':(2.10,.09,21.45),'T5-Class':(2.09,.09,21.45),'T7-Class':(2.09,.09,21.45),
 'I-Class':(None,.09,21.45),'C-Class':(2.00,.09,21.45),'R5-Class':(2.09,.09,21.45),
 'R7-Class':(2.09,.09,21.45),'F-Class':(.85,.09,21.45),'S5-Class':(.85,.09,21.45),
 'S7-Class':(.85,.09,21.45),'O-Class':(.68,.09,21.45),'P5-Class':(.68,.09,21.45),
 'P7-Class':(.68,.09,21.45),'D-Class':(1.06,.09,21.45)}),
'Sun_Life_Granite_Conservative_Class_MRFP_s.pdf': ('sun_life','Sun Life Granite Conservative Class','2026-06-30',{
 'Series A':(1.91,.04,3.58),'Series AT5':(1.93,.04,3.58),'Series F':(1.02,.04,3.58),
 'Series FT5':(1.02,.04,3.58),'Series O':(.22,.04,3.58)}),
'2545-samrfp-en-ca.pdf':('franklin','FRANKLIN CANADIAN CORE PLUS BOND FUND','2026-06-30',{
 'Series A':(1.21,None,51.95),'Series F':(.67,None,51.95),
 'Series O':(None,None,51.95),'ETF Series':(.61,None,51.95)}),
'mgif-semi2026.pdf':('middlefield','MIDDLEFIELD GLOBAL INFRASTRUCTURE FUND','2026-06-30',{
 'Series A':(2.73,.15,26.38),'Series F':(1.63,.15,26.38)}),
'879_EN_MRFP_A.pdf':('manulife','Manulife Climate Action Class','2026-04-30',{
 'Advisor Series':(2.27,.09,26.21),'Series F':(1.14,.09,26.21),
 'Series FT':(1.13,.09,26.21),'Series O':(.15,.09,26.21),'Series T':(2.29,.09,26.21)}),
'H8MK_ENG_MRFP.pdf':('dynamic','Dynamic Dividend Income Class','2026-06-30',{
 'Series A':(2.19,.07,17.54),'Series F':(1.06,.07,17.54),
 'Series FT':(1.06,.07,17.54),'Series I':(.12,.07,17.54),'Series T':(2.16,.07,17.54)}),
'Purpose Active Balanced Fund MRFP 2026-06-30.pdf':('purpose','PURPOSE ACTIVE BALANCED FUND','2026-06-30',{
 'ETF Units':(.34,0.0,20.85),'Class A':(1.4,0.0,20.85),'Class F':(.34,0.0,20.85)}),
'sa-mrfp-xeqt-en-ca.pdf':('blackrock','iShares Core Equity ETF Portfolio','2026-06-30',{
 'iShares Core Equity ETF Portfolio':(.19,.02,2.30)}),
'mrfp-cbo-en-ca.pdf':('blackrock','iShares 1-5 Year Laddered Corporate Bond Index ETF','2025-12-31',{
 'iShares 1-5 Year Laddered Corporate Bond Index ETF':(.27,None,35.93)}),
'mrfp-xeqt-en-ca.pdf':('blackrock','iShares Core Equity ETF Portfolio','2025-12-31',{
 'iShares Core Equity ETF Portfolio':(.20,.01,13.60)}),
'rbf10500_e.pdf':('rbc','RBC CANADIAN CORPORATE BOND FUND','2025-12-31',{
 'Series A':(1.05,.01,27.67),'Series D':(.64,.01,27.67),
 'Series F':(.50,.01,27.67),'Series O':(.02,.01,27.67)}),
'NBC901-yearly-report.pdf':('nbi','NBI Sustainable Secure Portfolio','2025-12-31',{
 'Investor / Advisor Series':(1.85,.08,22.19),'Series F':(.82,.08,22.19),
 'Series O':(.11,.08,22.19),'Series R':(1.82,.08,22.19)}),
}

@pytest.mark.parametrize('filename',DATA)
def test_fmc_reference_document(filename):
    fmc,fund,report_date,expected=DATA[filename]
    path=FIXTURES/filename
    assert path.exists(),f'Fixture absent: {path}'
    with pymupdf.open(path) as pdf:
        profile,_=detect_fmc(pdf)
        assert profile is not None and profile.key==fmc
    rows,diagnostics,raw=analyze(path.read_bytes(),enable_ocr=False)
    assert len(rows)==len(expected)
    by_class={r['class_name']:r for r in rows}
    assert set(by_class)==set(expected)
    assert len({r['row_id'] for r in rows})==len(rows)
    for cls,ratios in expected.items():
        row=by_class[cls]
        assert row['fund_name']==fund
        assert row['report_date']==report_date
        assert row['fmc_key']==fmc
        assert not row['needs_review']
        for name,want in zip(('MER','TER','PTR'),ratios):
            actual=row[name]
            if want is None:
                assert actual is None,(filename,cls,name,actual)
            else:
                assert actual==pytest.approx(want,abs=0.001),(filename,cls,name,actual,want)


def test_same_class_in_two_funds_has_different_identity():
    from mer.fmc.blackrock import PROFILE
    from mer.fmc.base import stabilize_rows
    rows=[{'fund_name':'Example Bond Fund','class_name':'Series A','report_date':'2026-06-30'},
          {'fund_name':'Example Equity Fund','class_name':'Series A','report_date':'2026-06-30'}]
    stabilize_rows(rows,PROFILE)
    assert rows[0]['row_id']!=rows[1]['row_id']


def test_unknown_company_requires_review():
    doc=pymupdf.open()
    page=doc.new_page()
    page.insert_text((40,80),'Example Unknown Mutual Fund')
    page.insert_text((40,120),'Management Expense Ratio 1.20%')
    data=doc.tobytes();doc.close()
    rows,diag,_=analyze(data,enable_ocr=False)
    assert diag[0].get('warning')
    assert all(r.get('needs_review') for r in rows)


def test_section_boundaries_can_split_single_page():
    from mer.shared.fund_sections import find_sections, extract_section_pdf
    doc=pymupdf.open()
    page=doc.new_page()
    page.insert_text((45,60),'Example Bond Fund',fontsize=14)
    page.insert_text((45,85),'Management Discussion of Fund Performance',fontsize=11)
    page.insert_text((45,140),'Bond section first.',fontsize=10)
    page.insert_text((45,380),'Example Equity Fund',fontsize=14)
    page.insert_text((45,410),'Financial Highlights',fontsize=11)
    page.insert_text((45,450),'Equity section later.',fontsize=10)
    sections=find_sections(doc,'Example Bond Fund','synthetic',r'Example (?:Bond|Equity) Fund')
    assert len(sections)==2
    assert sections[0].end_page==sections[1].start_page==0
    data,mapping=extract_section_pdf(doc,sections[0]);doc.close()
    with pymupdf.open(stream=data,filetype='pdf') as sub:
        contents=' '.join(p.get_text('text') for p in sub)
        assert 'Bond section first' in contents
        assert 'Equity section later' not in contents
    assert mapping==[1]
