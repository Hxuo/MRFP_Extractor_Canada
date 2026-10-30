from mer.extractor import metric_kind,to_number,select

def test_numbers():
 assert to_number('0.20%(g)')==0.20
 assert to_number('—') is None
 assert to_number('1.05')==1.05

def test_priority():
 assert metric_kind('Management Expense Ratio After Taxes / Waivers / Absorptions')==('MER',0)
 assert metric_kind('Management Expense Ratio After Taxes')==('MER',1)
 assert metric_kind('Management Expense Ratio After Waivers')==('MER',2)
 assert metric_kind('Management Expense Ratio Before Waivers')==(None,None)
 assert metric_kind('Trading Expense Ratio')[0]=='TER'
 assert metric_kind('Portfolio Turnover Rate')[0]=='PTR'

def test_select_priority():
 raw=[]
 for value,priority in [(2,4),(1.8,0)]:
  raw.append(dict(class_name='Series A',year=2026,metric='MER',value=value,priority=priority,page=2,x=30,y=44,source='demo',method='native'))
 chosen=select(raw)
 assert len(chosen)==1 and chosen[0]['MER']==1.8
