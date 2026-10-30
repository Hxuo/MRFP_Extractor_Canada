"""Optional regression tests for externally supplied financial-report fixtures."""
from pathlib import Path
import pytest
from mer.extractor import analyze
SAMPLES=Path(__file__).parent/'samples'
EXPECTED={
 'rbf10500_e.pdf':{'Series A':(1.05,0.01,27.67),'Series D':(0.64,0.01,27.67),'Series F':(0.50,0.01,27.67),'Series O':(0.02,0.01,27.67)},
 'NBC901-yearly-report.pdf':{'Investor / Advisor Series':(1.85,0.08,22.19),'Series F':(0.82,0.08,22.19),'Series O':(0.11,0.08,22.19),'Series R':(1.82,0.08,22.19)},
 'Purpose Active Balanced Fund MRFP 2026-06-30.pdf':{'ETF Units':(0.34,0.0,20.85),'Class A':(1.40,0.0,20.85),'Class F':(0.34,0.0,20.85)},
 'mrfp-xeqt-en-ca.pdf':{'iShares Core Equity ETFPortfolio':(0.20,0.01,13.60)},
 'sa-mrfp-xeqt-en-ca.pdf':{'iShares Core Equity ETFPortfolio':(0.19,0.02,2.30)},
 'mrfp-cbo-en-ca.pdf':{'iShares 1-5Year Laddered Corporate Bond Index ETF':(0.27,None,35.93)},
}
@pytest.mark.parametrize('filename,expected',EXPECTED.items())
def test_sample(filename,expected):
 path=SAMPLES/filename
 if not path.exists(): pytest.skip('Sample PDF not bundled')
 rows,_,_=analyze(path.read_bytes(),enable_ocr=False)
 actual={r['class_name']:(r['MER'],r['TER'],r['PTR']) for r in rows}
 assert actual==expected
