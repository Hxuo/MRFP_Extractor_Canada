# MER Extraction v7 — FMC-specific MRFP scanner

**Offline-local Flask web app · PyMuPDF primary · optional PaddleOCR fallback · no Docling**

This is a modular development build based on the user's last working non-Docling MER Extraction project. It preserves the local browser UI, saved PDF preview, SQLite history, workspace clearing, manual corrections/verification, confirmed rescan, and Excel/Lipper-format export.

## What's new in v7

- **FMC detector** (`mer/fmc_router.py`): automatically chooses a registered company from publisher evidence near the beginning of the PDF. Ambiguous/unknown PDFs go through an **unverified, needs-review** native extraction instead of being claimed supported.
- **10 registered company profiles** (`mer/fmc/*.py`), each with its own identity, fund name rules, and an upgrade point for layout-specific extraction. The first version contains native dedicated class/ratio-section parsing for **Desjardins, Sun Life, National Bank Investments**; the other seven profiles reuse tested parts of the original native extractor where appropriate. This is intentional; the company module is the extension point rather than copying the entire engine ten times.
- **Dynamic fund/class names**: names and ratios are derived from the document, **never** a fixed list of fund titles, class counts, or hard-coded ratio values.
- **Fund section representation** (`mer/shared/fund_sections.py`): page/Y-coordinate physical section ranges, multi-section slicing when distinct issuer-specific fund titles have sufficient structural evidence. **Real multi-fund PDF layouts still need acceptance testing**; the supplied 12 PDFs each describe one primary fund.
- **Independent fund and class IDs**: each extracted row includes `fmc_key`, `fund_id`, `class_id`, and `row_id` to keep two different funds' `Series A` rows separate. Corrections use `row_id` in the UI, with a backwards-compatible class-name route for older saved rows.
- **Excel support** explicitly included in `requirements.txt` (`openpyxl`). Original missing values remain blank.
- **12 furnished PDF fixtures** and explicit reference values in `tests/test_fmc_v7.py`.

## Requirements and first run (Windows PowerShell)

Use **Python 3.11** on Windows. Extract the entire `MER_Extraction_v7` folder to `Documents`, then:

```powershell
cd "$HOME\Documents\MER_Extraction_v7"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000`. Subsequent starts can use `start.bat`. The app runs locally and does not require external services after installing its Python packages.

### Optional PaddleOCR fallback for image-only PDFs

```powershell
.\.venv\Scripts\python.exe -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

Native PDF text remains the primary processing path, and PaddleOCR runs only for image-only/low-text pages, as in the original engine. **PaddleOCR was not exercised in this package's focused native-PDF checks.**

## Upgrade without overwriting your history

1. **Stop the old Flask application**, and keep its entire old project folder as backup.
2. Extract **V7 to a new folder**, not over your existing V1/V6 directory.
3. If you want your old history in V7, **before starting V7 for the first time**, copy the old `data/mer_scanner.db` plus the entire `data/pdfs/` folder into `MER_Extraction_v7/data/`. These are **intentionally excluded from the downloadable ZIP** to protect your live data.
4. Do **not** copy your `.venv`; follow the dependency-install steps for V7.
5. Start V7. Verified/manually corrected historical results are preserved by the existing code. To explicitly replace one of those, use the **Re-scan → Preview → Confirm** workflow; unverified older records are reprocessed on upload under engine version 7.
6. The `data/mer_scanner.db` file is a writable SQLite DB. Keep regular backups of it and `data/pdfs`. Never replace your existing database with a blank one.

## Regression testing (run on your laptop)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests/test_fmc_v7.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_engine.py tests/test_excel_report.py tests/test_storage.py -v
.\.venv\Scripts\python.exe -m pytest tests -v
```

Twelve source PDFs live in `tests/fixtures`. Some **legacy** tests reference saved-history documents by hash; `tests/test_extractor_regression.py` includes a test fixture fallback so those tests can execute without a shipped copy of your personal SQLite history. Always check failures against the actual original PDF.

**Build-time focused check (Linux, native extraction only): 26 passed.** This is **not** a Windows/PaddleOCR/Flask GUI acceptance result or a full regression certification; perform your own complete tests.

## How to add a new FMC

1. Save a representative actual MRFP PDF in `tests/fixtures/`.
2. Add a new module `mer/fmc/new_issuer.py` implementing a `FMCProfile` or a subclass with specialized `fund_name()` / `extract()` rules. Avoid hard-coding individual funds and ratios.
3. Register `PROFILE` in `mer/fmc/__init__.py`.
4. Add full source-derived expected class names, date, MER, TER, PTR to the V7 test suite or a new issuer test file. Validate both annual/semiannual layouts when possible.
5. Check the FMC detection score is unambiguous, and test against all existing PDFs to ensure unchanged output.
6. Increase/maintain `ENGINE_VERSION` if changing existing extraction logic so old unverified cache entries can be refreshed; verified/corrected records require confirmed Re-scan.

## Folder architecture

```
mer/
  extractor.py                 # original, native-PDF extraction helpers
  fmc_router.py                # FMC detection, routing, identity, boundaries
  fmc/                         # 10 company profiles
  shared/fund_sections.py      # validated fund-section boundaries
  shared/table_stream.py       # native label-based ratio table parser
  storage.py                   # SQLite persistence, corrections, rescan
  excel_export.py              # Extraction Results / Lipper Format
app.py                         # Flask backend
static/ templates/             # Existing frontend
requirements*.txt
start.bat
scripts/                       # Optional operational utilities
tests/fixtures/                # 12 MRFP PDFs provided for acceptance
```

## Safety and accuracy notes

- Source ratio values are **numbers, without percent signs**. Missing ratio cells are `None`, not zero. Before-waiver MERs are not substituted for after-waiver/standard MERs.
- Report date is selected from documented table/report evidence where supported. Unknown or conflicting dates should be reviewed.
- An FMC's presence in the registry indicates **sampled layouts**, not an unconditional guarantee for all its future funds or changed templates.
- The 12 reference documents provide **10 FMCs, 49 output rows**. Real multi-fund documents, scanned PDFs, French-language layouts and unsupported future changes still require additional validation.
- Do not treat automatic financial ratios as independently verified until you review the source page and select Verify.
