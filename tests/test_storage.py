from mer import storage

def test_sqlite_roundtrip(tmp_path,monkeypatch):
 monkeypatch.setattr(storage,'PATH',tmp_path/'mer.db')
 storage.initialize()
 rows=[{'class_name':'Series A','year':2026,'MER':1.25,'TER':0.01,'PTR':14.5,'evidence':{}}]
 storage.save('testhash','sample.pdf',rows,[])
 assert storage.get('testhash')['verified'] is False
 changed=storage.correct('testhash','Series A','MER',1.12)
 assert changed[0]['MER']==1.12
 assert storage.verify('testhash')
 assert storage.get('testhash')['verified'] is True
