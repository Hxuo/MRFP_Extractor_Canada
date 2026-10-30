"""MER Extraction v7 — Flask localhost application, asynchronous scans and SQLite cache."""
import csv,io,os,hashlib,threading,uuid,time,logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from flask import Flask,request,render_template,send_file,jsonify,abort
from werkzeug.utils import secure_filename
from mer.fmc_router import analyze
from mer import storage
from mer.excel_export import build_excel

BASE=Path(__file__).resolve().parent
DATA=BASE/'data';DATA.mkdir(exist_ok=True)
app=Flask(__name__,template_folder='templates',static_folder='static')
app.config['MAX_CONTENT_LENGTH']=40*1024*1024
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mer-worker')
JOBS={};LOCK=threading.RLock()

# Temporary Re-scan previews (not saved to SQLite).
RESCAN_PREVIEWS = {}
RESCAN_PREVIEW_TTL = 900  # 15 minutes

storage.initialize()

def snapshot(job):
 with LOCK:
  d=JOBS.get(job)
  if not d:return None
  return {k:v for k,v in d.items() if k not in ('pdf','future')}


def background(job,content,name,hash_,expected_generation):
 def progress(page,total,message):
  with LOCK:
   JOBS[job].update(
    page=page,
    total=total,
    message=message,
    updated=time.time()
   )

 try:
  with LOCK:
   JOBS[job].update(
    status='processing',
    message='Analyzing PDF'
   )

  result,diagnostics,raw=analyze(
   content,
   progress,
   enable_ocr=True
  )

  saved=storage.save(hash_,name,result,diagnostics)

  # Always return the actual persisted results.
  # A protected document may retain its verified/manual data.

  stored=storage.get(hash_)

  if stored is None:
   raise RuntimeError('Saved document could not be loaded')


  # Compare the upload's workspace generation with the
  # current SQLite generation before adding to Recent.
  # The check and insert happen in one database transaction.
  with LOCK:
   if not JOBS[job].get('workspace_cleared',False):
    storage.workspace_add(
     hash_,
     expected_generation=expected_generation
    )

  with LOCK:


   JOBS[job].update(
    status='complete',
    result=stored['results'],
    diagnostics=stored['diagnostics'],
    raw_count=len(raw),
    verified=stored['verified'],
    saved=saved,
    message=(
     'Complete'
     if saved
     else 'Existing verified/corrected results preserved'
    ),
    updated=time.time()
   )

 except Exception as exc:
  app.logger.exception('Scan failed')
  with LOCK:
   JOBS[job].update(
    status='failed',
    error=str(exc),
    message='Scan failed',
    updated=time.time()
   )


@app.get('/')
def index():return render_template('index.html')

@app.post('/api/extract')
def extract():
 f=request.files.get('pdf')
 if not f:return jsonify(error='Please select a PDF'),400
 content=f.read()
 if len(content)>40*1024*1024:return jsonify(error='PDF too large (max 40MB)'),413
 if not content.startswith(b'%PDF-'):return jsonify(error='Not a valid PDF'),400

 hash_=hashlib.sha256(content).hexdigest(); name=secure_filename(f.filename or 'document.pdf')

 # Save the original PDF even when extraction is already cached.
 storage.save_pdf(hash_, content)

 existing=storage.get(hash_)
 expected_generation=storage.workspace_generation()

 if existing and (
   existing['verified']
   or existing['has_corrections']
   or (
    existing['engine_version'] >= storage.ENGINE_VERSION
    and existing['results']
   )
  ):
  storage.workspace_add(hash_)
  job=uuid.uuid4().hex
  with LOCK:
   JOBS[job]=dict(
    hash=hash_,
    filename=name,
    status='complete',
    message='Loaded from local cache',
    page=0,
    total=0,
    updated=time.time(),
    result=existing['results'],
    diagnostics=existing['diagnostics'],
    verified=existing['verified']
   )
  return jsonify(job=job,cached=True)

 # No verified results and no extracted rows:
 # reprocess the uploaded PDF using the updated engine.
 if existing:
  app.logger.info(
   'Retrying previously unsuccessful extraction: %s',
   name
  )

 job=uuid.uuid4().hex
 with LOCK:JOBS[job]=dict(hash=hash_,filename=name,status='queued',message='Queued',page=0,total=0,updated=time.time())
 executor.submit(background,job,content,name,hash_,expected_generation)
 return jsonify(job=job,cached=False)

@app.get('/api/jobs/<job>')
def job_status(job):
 d=snapshot(job)
 if d is None:return jsonify(error='Unknown scan'),404
 return jsonify(d)

@app.get('/api/history')
def history():
 return jsonify(storage.workspace_recent())

@app.get('/api/history/all')
def all_history():
 return jsonify(storage.history_all())

@app.post('/api/workspace/restore/<hash_>')
def restore_workspace(hash_):
 if not storage.workspace_add(hash_):
  return jsonify(error='Saved document not found'),404

 return jsonify(ok=True)

@app.post('/api/workspace/clear')
def clear_workspace():
 with LOCK:
  # A running scan must not add itself back after clearing.
  for job in JOBS.values():
   if job.get('status') in ('queued','processing'):
    job['workspace_cleared']=True

  cleared=storage.workspace_clear()

 return jsonify(
  ok=True,
  cleared=cleared
 )

@app.get('/api/documents/<hash_>')
def document(hash_):
 d=storage.get(hash_)
 if not d:return jsonify(error='Not found'),404
 return jsonify(d)


@app.get('/api/documents/<hash_>/pdf')
def document_pdf(hash_):
 path = storage.get_pdf_path(hash_)

 if path is None:
  return jsonify(error='Original PDF is not stored'),404

 if storage.get(hash_) is None:
  return jsonify(error='Document not found in history'),404

 response = send_file(
  path,
  mimetype='application/pdf',
  as_attachment=False,
  download_name='document.pdf',
  conditional=True
 )

 response.headers['Cache-Control'] = 'private, no-store'
 response.headers['X-Content-Type-Options'] = 'nosniff'

 return response


@app.post('/api/documents/<hash_>/verify')
def verify(hash_):
 if not storage.verify(hash_):return jsonify(error='Document not found'),404
 return jsonify(ok=True)

@app.post('/api/documents/<hash_>/correct')
def correction(hash_):
 d=request.get_json(silent=True) or {}
 try:rows=storage.correct(hash_,d.get('class_name',''),d.get('metric',''),d.get('value'))
 except (ValueError,TypeError,OverflowError) as exc:return jsonify(error=str(exc)),400
 return jsonify(ok=True,results=rows)

@app.post('/api/documents/<hash_>/correct-row')
def correction_row(hash_):
 d=request.get_json(silent=True)

 if not isinstance(d,dict):
  return jsonify(error='Invalid request body'),400

 class_name=d.get('class_name')
 row_id=d.get('row_id')
 values=d.get('values')

 if not isinstance(class_name,str) or not class_name.strip():
  return jsonify(error='Class / Series is required'),400

 if not isinstance(values,dict):
  return jsonify(error='Correction values are required'),400

 try:
  rows=storage.correct_row(
   hash_,
   class_name,
   values,
   row_id=row_id if isinstance(row_id,str) and row_id else None
  )
 except (ValueError,TypeError,OverflowError) as exc:
  return jsonify(error=str(exc)),400

 return jsonify(
  ok=True,
  results=rows,
  message='Row correction saved'
 )

@app.get('/api/documents/<hash_>/csv')
def export(hash_):
 d=storage.get(hash_)
 if not d:abort(404)
 stream=io.StringIO(newline='');writer=csv.writer(stream)
 writer.writerow(['Fund Name','Class / Series','Year','MER','TER','PTR','MER source','MER page','TER page','PTR page','Verification'])
 for r in d['results']:
  ev=r.get('evidence',{})
  writer.writerow([r.get('fund_name',''),r['class_name'],r['year'],r.get('MER'),r.get('TER'),r.get('PTR'),ev.get('MER',{}).get('source',''),ev.get('MER',{}).get('page',''),ev.get('TER',{}).get('page',''),ev.get('PTR',{}).get('page',''),'Verified' if d['verified'] else 'Unverified'])
 return send_file(io.BytesIO(('\ufeff'+stream.getvalue()).encode('utf-8')),mimetype='text/csv',as_attachment=True,download_name='MER_TER_PTR_'+hash_[:8]+'.csv')


# ---------------------------------------------------------
# Export multiple saved documents as one CSV
# ---------------------------------------------------------

def export_documents_csv(scope):
 if scope == 'all':
  documents = storage.history_all()
 elif scope == 'listed':
  documents = storage.workspace_recent()
 else:
  abort(400)

 stream = io.StringIO(newline='')
 writer = csv.writer(stream)

 writer.writerow([
  'Fund / Filename',
  'Class / Series',
  'Year',
  'MER',
  'TER',
  'PTR',
  'MER Source',
  'MER Page',
  'TER Page',
  'PTR Page',
  'Verification'
 ])

 for item in documents:
  doc = storage.get(item['hash'])
  if doc is None:
   continue

  for row in doc['results']:
   evidence = row.get('evidence') or {}

   writer.writerow([
    doc['filename'],
    row.get('class_name', ''),
    row.get('year', ''),
    row.get('MER'),
    row.get('TER'),
    row.get('PTR'),
    evidence.get('MER', {}).get('source', ''),
    evidence.get('MER', {}).get('page', ''),
    evidence.get('TER', {}).get('page', ''),
    evidence.get('PTR', {}).get('page', ''),
    'Verified' if doc['verified'] else 'Unverified'
   ])

 filename = (
  'MER_TER_PTR_All_Funds.csv'
  if scope == 'all'
  else 'MER_TER_PTR_Listed_Funds.csv'
 )

 return send_file(
  io.BytesIO(('\ufeff' + stream.getvalue()).encode('utf-8')),
  mimetype='text/csv',
  as_attachment=True,
  download_name=filename
 )


@app.get('/api/exports/all.csv')
def export_all_csv():
 return export_documents_csv('all')


@app.get('/api/exports/listed.csv')
def export_listed_csv():
 return export_documents_csv('listed')


# ---------------------------------------------------------
# Excel exports: current, all saved, and listed documents
# ---------------------------------------------------------

XLSX_MIMETYPE = (
    'application/vnd.openxmlformats-officedocument.'
    'spreadsheetml.sheet'
)


@app.get('/api/documents/<hash_>/xlsx')
def export_document_xlsx(hash_):
    document = storage.get(hash_)

    if document is None:
        abort(404)

    stream = build_excel([document])

    return send_file(
        stream,
        mimetype=XLSX_MIMETYPE,
        as_attachment=True,
        download_name=f'MER_TER_PTR_{hash_[:8]}.xlsx'
    )


@app.get('/api/exports/all.xlsx')
def export_all_xlsx():
    summaries = storage.history_all()

    documents = [
        document
        for summary in summaries
        if (document := storage.get(summary['hash'])) is not None
    ]

    stream = build_excel(documents)

    return send_file(
        stream,
        mimetype=XLSX_MIMETYPE,
        as_attachment=True,
        download_name='MER_TER_PTR_All_Funds.xlsx'
    )


@app.get('/api/exports/listed.xlsx')
def export_listed_xlsx():
    # Use the same saved workspace scope as the existing
    # Export All Listed feature.
    summaries = storage.workspace_all_listed()

    documents = [
        document
        for summary in summaries
        if (document := storage.get(summary['hash'])) is not None
    ]

    stream = build_excel(documents)

    return send_file(
        stream,
        mimetype=XLSX_MIMETYPE,
        as_attachment=True,
        download_name='MER_TER_PTR_Listed_Funds.xlsx'
    )



@app.post('/api/documents/<hash_>/rescan/preview')
def rescan_preview(hash_):
 path = storage.get_pdf_path(hash_)

 if path is None or storage.get(hash_) is None:
  return jsonify(error='Saved PDF not found'),404

 try:
  # Capture the original state BEFORE extraction.
  token = storage.get_rescan_token(hash_)

  results, diagnostics, raw = analyze(
   path.read_bytes(),
   enable_ocr=True
  )

  if not results:
   return jsonify(
    error='Re-scan found no reliable results. '
          'Saved data was not changed.'
   ),422

  # The document may have been edited during extraction.
  if storage.get_rescan_token(hash_) != token:
   return jsonify(
    error='Document changed during Re-scan. '
          'Please preview again.'
   ),409

  preview_id = uuid.uuid4().hex
  now = time.time()

  with LOCK:
   # Remove expired previews.
   for key, preview in list(RESCAN_PREVIEWS.items()):
    if now - preview['created'] > RESCAN_PREVIEW_TTL:
     del RESCAN_PREVIEWS[key]

   RESCAN_PREVIEWS[preview_id] = {
    'hash': hash_,
    'results': results,
    'diagnostics': diagnostics,
    'token': token,
    'created': now
   }

  return jsonify(
   ok=True,
   preview_id=preview_id,
   results=results,
   raw_count=len(raw),
   expires_in=RESCAN_PREVIEW_TTL
  )

 except Exception:
  app.logger.exception('Re-scan preview failed')
  return jsonify(error='Re-scan preview failed'),500


@app.post('/api/documents/<hash_>/rescan/confirm')
def rescan_confirm(hash_):
 data = request.get_json(silent=True)

 if not isinstance(data, dict):
  return jsonify(error='Invalid confirmation request'),400

 preview_id = data.get('preview_id')

 if not isinstance(preview_id, str):
  return jsonify(error='Missing preview ID'),400

 with LOCK:
  preview = RESCAN_PREVIEWS.get(preview_id)

  if preview is None or preview['hash'] != hash_:
   return jsonify(error='Re-scan preview not found'),404

  if time.time() - preview['created'] > RESCAN_PREVIEW_TTL:
   del RESCAN_PREVIEWS[preview_id]
   return jsonify(
    error='Re-scan preview expired. Please preview again.'
   ),409

  try:
   storage.replace_after_rescan(
    hash_,
    preview['results'],
    preview['diagnostics'],
    preview['token']
   )
  except ValueError as exc:
   return jsonify(error=str(exc)),409
  except Exception:
   app.logger.exception('Re-scan replacement failed')
   return jsonify(error='Could not save Re-scan results'),500

  # A successful preview can be confirmed only once.
  del RESCAN_PREVIEWS[preview_id]

 return jsonify(
  ok=True,
  message='Re-scan results saved. Verification reset.',
  document=storage.get(hash_)
 )


@app.errorhandler(413)
def large(_):return jsonify(error='File exceeds 40MB limit'),413

if __name__=='__main__':
 print('\nMER Extraction v7 ready at http://127.0.0.1:5000\n')
 app.run(host='127.0.0.1',port=5000,threaded=True,debug=False,use_reloader=False)
