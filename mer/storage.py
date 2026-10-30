import json,sqlite3,time,hashlib,threading,math
from contextlib import contextmanager
from pathlib import Path
PATH=Path(__file__).resolve().parent.parent/'data'/'mer_scanner.db'
LOCK=threading.RLock()

ENGINE_VERSION = 7
def conn():
 PATH.parent.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(PATH,timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA foreign_keys=ON');return c

@contextmanager
def db_session():
    connection = conn()
    try:
        with connection:
            yield connection
    finally:
        connection.close()

def initialize():
 with LOCK, db_session() as c:
  # Detect first-time workspace migration.
  workspace_exists = c.execute(
   "SELECT 1 FROM sqlite_master "
   "WHERE type='table' AND name='workspace_documents'"
  ).fetchone() is not None

  c.executescript('''
CREATE TABLE IF NOT EXISTS documents(
 hash TEXT PRIMARY KEY,
 filename TEXT NOT NULL,
 created REAL NOT NULL,
 updated REAL NOT NULL,
 verified INTEGER NOT NULL DEFAULT 0,
 results TEXT NOT NULL,
 diagnostics TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corrections(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 doc_hash TEXT NOT NULL,
 class_name TEXT NOT NULL,
 year INTEGER NOT NULL,
 row_id TEXT,
 metric TEXT NOT NULL,
 old_value REAL,
 new_value REAL,
 changed REAL NOT NULL,
 FOREIGN KEY(doc_hash) REFERENCES documents(hash)
);

CREATE INDEX IF NOT EXISTS idx_corrections_hash
ON corrections(doc_hash);

CREATE TABLE IF NOT EXISTS workspace_documents(
 doc_hash TEXT PRIMARY KEY,
 listed_at REAL NOT NULL,
 FOREIGN KEY(doc_hash) REFERENCES documents(hash)
);

CREATE INDEX IF NOT EXISTS idx_workspace_listed_at
ON workspace_documents(listed_at DESC);

CREATE TABLE IF NOT EXISTS workspace_state(
 id INTEGER PRIMARY KEY CHECK(id=1),
 generation INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO workspace_state(id,generation)
VALUES(1,0);


CREATE TABLE IF NOT EXISTS rescan_snapshots(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 doc_hash TEXT NOT NULL,
 filename TEXT NOT NULL,
 results TEXT NOT NULL,
 diagnostics TEXT NOT NULL,
 verified INTEGER NOT NULL,
 engine_version INTEGER NOT NULL,
 saved_at REAL NOT NULL,
 FOREIGN KEY(doc_hash) REFERENCES documents(hash)
);

CREATE INDEX IF NOT EXISTS idx_rescan_snapshots_hash
ON rescan_snapshots(doc_hash);


''')

  columns = {
   row['name']
   for row in c.execute('PRAGMA table_info(documents)')
  }

  correction_columns = {r['name'] for r in c.execute('PRAGMA table_info(corrections)')}
  if 'row_id' not in correction_columns:
   c.execute('ALTER TABLE corrections ADD COLUMN row_id TEXT')

  if 'engine_version' not in columns:
   c.execute(
    'ALTER TABLE documents '
    'ADD COLUMN engine_version INTEGER NOT NULL DEFAULT 1'
   )

  # On first migration only, preserve the existing Recent list.
  # Never automatically repopulate a cleared workspace.
  if not workspace_exists:
   c.execute('''
    INSERT OR IGNORE INTO workspace_documents(doc_hash, listed_at)
    SELECT hash, updated FROM documents
   ''')


def save(hash_, filename, results, diagnostics):
 initialize()
 with LOCK, db_session() as c:
  existing = c.execute(
   'SELECT verified FROM documents WHERE hash=?',
   (hash_,)
  ).fetchone()

  if existing:
   has_corrections = c.execute(
    'SELECT 1 FROM corrections WHERE doc_hash=? LIMIT 1',
    (hash_,)
   ).fetchone() is not None

   # Never silently overwrite verified or manually corrected data.
   if existing['verified'] or has_corrections:
    return False

  now = time.time()

  c.execute('''
   INSERT INTO documents(
    hash, filename, created, updated, verified,
    results, diagnostics, engine_version
   )
   VALUES(?,?,?,?,?,?,?,?)
   ON CONFLICT(hash) DO UPDATE SET
    filename=excluded.filename,
    updated=excluded.updated,
    results=excluded.results,
    diagnostics=excluded.diagnostics,
    engine_version=excluded.engine_version,
    verified=0
  ''', (
   hash_, filename, now, now, 0,
   json.dumps(results), json.dumps(diagnostics),
   ENGINE_VERSION
  ))

 return True


def get(hash_):
 initialize()

 with db_session() as c:
  r = c.execute(
   'SELECT * FROM documents WHERE hash=?',
   (hash_,)
  ).fetchone()

  if not r:
   return None

  has_corrections = c.execute(
   'SELECT 1 FROM corrections WHERE doc_hash=? LIMIT 1',
   (hash_,)
  ).fetchone() is not None

 return dict(
  hash=r['hash'],
  filename=r['filename'],
  verified=bool(r['verified']),
  results=json.loads(r['results']),
  diagnostics=json.loads(r['diagnostics']),
  engine_version=r['engine_version'],
  has_corrections=has_corrections
 )

def recent(limit=100):
 initialize()
 with db_session() as c:rows=c.execute('SELECT hash,filename,created,updated,verified FROM documents ORDER BY updated DESC LIMIT ?',(limit,)).fetchall()
 return [dict(x) for x in rows]
def verify(hash_):
 initialize()
 with LOCK,db_session() as c:
  res=c.execute('UPDATE documents SET verified=1,updated=? WHERE hash=?',(time.time(),hash_))
  return res.rowcount>0
def correct(hash_,class_name,metric,value):
 if metric not in ('MER','TER','PTR'):raise ValueError('Invalid metric')
 v=None if value is None or value=='' else float(value)
 if v is not None and (v<0 or v>100):raise ValueError('Ratio out of expected range (0–100)')
 initialize()
 with LOCK,db_session()as c:
  row=c.execute('SELECT results FROM documents WHERE hash=?',(hash_,)).fetchone()
  if not row:raise ValueError('Document not found')
  records=json.loads(row['results']);target=next((x for x in records if x['class_name']==class_name),None)
  if target is None:raise ValueError('Class not found')
  before=target[metric];target[metric]=v
  target.setdefault('evidence',{})[metric]={'source':'user correction','page':None,'method':'manual','position':None}
  c.execute('INSERT INTO corrections(doc_hash,class_name,year,row_id,metric,old_value,new_value,changed) VALUES(?,?,?,?,?,?,?,?)',(hash_,class_name,target['year'],target.get('row_id'),metric,before,v,time.time()))
  c.execute('UPDATE documents SET results=?,verified=0,updated=? WHERE hash=?',(json.dumps(records),time.time(),hash_))
 return records


# ---------------------------------------------------------
# Persistent original PDF storage for History preview
# ---------------------------------------------------------

PDF_DIR = PATH.parent / "pdfs"


def save_pdf(hash_, content):
    """Save an original PDF once, using its SHA-256 hash."""
    import os
    import uuid

    if not isinstance(content, bytes) or not content.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF content")

    actual_hash = hashlib.sha256(content).hexdigest()

    if hash_ != actual_hash:
        raise ValueError("PDF hash mismatch")

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    destination = PDF_DIR / (hash_ + ".pdf")

    if destination.is_file():
        return destination

    temporary = PDF_DIR / (hash_ + "." + uuid.uuid4().hex + ".tmp")

    try:
        temporary.write_bytes(content)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    return destination


def get_pdf_path(hash_):
    """Return a stored PDF path, if available."""
    import re

    if not isinstance(hash_, str):
        return None

    if not re.fullmatch(r"[0-9a-f]{64}", hash_):
        return None

    destination = PDF_DIR / (hash_ + ".pdf")

    if not destination.is_file():
        return None

    return destination


# ---------------------------------------------------------
# Active workspace and permanent saved history
# ---------------------------------------------------------

def workspace_recent(limit=100):
 initialize()
 with db_session() as c:
  rows = c.execute('''
   SELECT d.hash, d.filename, d.created, d.updated,
          d.verified, w.listed_at
   FROM workspace_documents AS w
   JOIN documents AS d ON d.hash = w.doc_hash
   ORDER BY w.listed_at DESC, d.hash
   LIMIT ?
  ''', (limit,)).fetchall()
 return [dict(r) for r in rows]


def workspace_all_listed():
    """
    Return all active workspace documents, newest first.

    Unlike workspace_recent(), this function has no
    100-document limit and is intended for full exports.
    """
    initialize()

    with db_session() as c:
        rows = c.execute("""
            SELECT d.hash, d.filename, d.created, d.updated,
                   d.verified, w.listed_at
            FROM workspace_documents AS w
            JOIN documents AS d
              ON d.hash = w.doc_hash
            ORDER BY w.listed_at DESC, d.hash
        """).fetchall()

    return [dict(row) for row in rows]


def workspace_add(hash_, expected_generation=None):
 """Add a document only if the workspace has not been cleared."""
 initialize()
 with LOCK, db_session() as c:
  current = c.execute(
   'SELECT generation FROM workspace_state WHERE id=1'
  ).fetchone()['generation']

  if (
   expected_generation is not None
   and current != expected_generation
  ):
   return False

  exists = c.execute(
   'SELECT 1 FROM documents WHERE hash=?',
   (hash_,)
  ).fetchone()

  if not exists:
   return False

  c.execute('''
   INSERT INTO workspace_documents(doc_hash, listed_at)
   VALUES(?, ?)
   ON CONFLICT(doc_hash) DO UPDATE SET
    listed_at=excluded.listed_at
  ''', (hash_, time.time()))

 return True

def workspace_clear():
 """Clear active documents and invalidate old uploads atomically."""
 initialize()
 with LOCK, db_session() as c:
  count = c.execute(
   'SELECT COUNT(*) FROM workspace_documents'
  ).fetchone()[0]

  c.execute('DELETE FROM workspace_documents')

  c.execute('''
   UPDATE workspace_state
   SET generation=generation+1
   WHERE id=1
  ''')

 return count

def history_all():
 """Return all permanently saved documents, newest first."""
 initialize()
 with db_session() as c:
  rows = c.execute('''
   SELECT hash, filename, created, updated, verified
   FROM documents
   ORDER BY created DESC, hash
  ''').fetchall()
 return [dict(r) for r in rows]

def workspace_generation():
 """Return the current persistent workspace generation."""
 initialize()
 with db_session() as c:
  row = c.execute(
   'SELECT generation FROM workspace_state WHERE id=1'
  ).fetchone()
 return int(row['generation'])


def correct_row(hash_, class_name, values, row_id=None):
 """Atomically save changes to MER, TER and PTR for one row."""
 if not isinstance(values, dict):
  raise ValueError('Invalid correction data')

 allowed = ('MER', 'TER', 'PTR')

 if not values or any(k not in allowed for k in values):
  raise ValueError('Only MER, TER and PTR can be corrected')

 cleaned = {}
 for metric, value in values.items():
  if value is None or (isinstance(value, str) and not value.strip()):
   cleaned[metric] = None
   continue

  try:
   number = float(value)
  except (ValueError, TypeError, OverflowError):
   raise ValueError('Invalid value for ' + metric)

  upper = 1000 if metric == 'PTR' else 100

  if not math.isfinite(number) or not (0 <= number <= upper):
   raise ValueError(
    metric + ' must be between 0 and ' + str(upper)
   )

  cleaned[metric] = number

 initialize()

 with LOCK, db_session() as c:
  row = c.execute(
   'SELECT results FROM documents WHERE hash=?',
   (hash_,)
  ).fetchone()

  if row is None:
   raise ValueError('Document not found')

  records = json.loads(row['results'])

  targets = [
   r for r in records
   if (r.get('row_id') == row_id if row_id else r['class_name'] == class_name)
  ]

  if len(targets) != 1:
   raise ValueError('Class not found or ambiguous')

  target = targets[0]
  changes = []

  for metric, new_value in cleaned.items():
   old_value = target.get(metric)

   if old_value == new_value:
    continue

   changes.append((metric, old_value, new_value))

  if not changes:
   return records

  now = time.time()

  for metric, old_value, new_value in changes:
   target[metric] = new_value

   target.setdefault('evidence', {})[metric] = {
    'source': 'user correction',
    'page': None,
    'method': 'manual',
    'position': None
   }

   c.execute('''
    INSERT INTO corrections(
     doc_hash, class_name, year, row_id, metric,
     old_value, new_value, changed
    )
    VALUES(?,?,?,?,?,?,?,?)
   ''', (
    hash_,
    class_name,
    target['year'],
    target.get('row_id'),
    metric,
    old_value,
    new_value,
    now
   ))

  c.execute('''
   UPDATE documents
   SET results=?, verified=0, updated=?
   WHERE hash=?
  ''', (json.dumps(records), now, hash_))

 return records


# ---------------------------------------------------------
# Safe confirmed Re-scan
# ---------------------------------------------------------

def rescan_token(row):
 """Fingerprint the saved state for conflict detection."""
 state = json.dumps({
  'results': row['results'],
  'diagnostics': row['diagnostics'],
  'verified': row['verified'],
  'engine_version': row['engine_version'],
  'updated': row['updated']
 }, sort_keys=True)

 return hashlib.sha256(state.encode('utf-8')).hexdigest()


def get_rescan_token(hash_):
 """Get a token without changing saved data."""
 initialize()

 with db_session() as c:
  row = c.execute(
   'SELECT * FROM documents WHERE hash=?',
   (hash_,)
  ).fetchone()

  if row is None:
   raise ValueError('Document not found')

  return rescan_token(row)


def replace_after_rescan(
 hash_, new_results, new_diagnostics, expected_token
):
 """Replace only after explicit confirmation and state check."""

 if not isinstance(new_results, list) or not new_results:
  raise ValueError('Re-scan produced no results')

 if not isinstance(new_diagnostics, list):
  raise ValueError('Invalid extraction diagnostics')

 if not isinstance(expected_token, str) or len(expected_token) != 64:
  raise ValueError('Invalid Re-scan token')

 for result in new_results:
  if not isinstance(result, dict):
   raise ValueError('Invalid extraction row')

  if not isinstance(result.get('class_name'), str):
   raise ValueError('Missing class name')

  if not result['class_name'].strip():
   raise ValueError('Empty class name')

  if not isinstance(result.get('year'), int):
   raise ValueError('Invalid reporting year')

  for metric in ('MER', 'TER', 'PTR'):
   value = result.get(metric)

   if value is not None:
    if (
     not isinstance(value, (int, float))
     or isinstance(value, bool)
     or not math.isfinite(value)
     or value < 0
    ):
     raise ValueError('Invalid ' + metric + ' value')

 initialize()

 with LOCK, db_session() as c:
  row = c.execute(
   'SELECT * FROM documents WHERE hash=?',
   (hash_,)
  ).fetchone()

  if row is None:
   raise ValueError('Document not found')

  if rescan_token(row) != expected_token:
   raise ValueError(
    'Document changed since Re-scan preview. '
    'Please preview it again.'
   )

  now = time.time()

  # Preserve the previous complete extraction.
  c.execute('''
   INSERT INTO rescan_snapshots(
    doc_hash, filename, results, diagnostics,
    verified, engine_version, saved_at
   )
   VALUES(?,?,?,?,?,?,?)
  ''', (
   hash_,
   row['filename'],
   row['results'],
   row['diagnostics'],
   row['verified'],
   row['engine_version'],
   now
  ))

  # Replace saved results in the same transaction.
  c.execute('''
   UPDATE documents
   SET results=?,
       diagnostics=?,
       verified=0,
       engine_version=?,
       updated=?
   WHERE hash=?
  ''', (
   json.dumps(new_results),
   json.dumps(new_diagnostics),
   ENGINE_VERSION,
   now,
   hash_
  ))

 return True

