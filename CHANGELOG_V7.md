# MER Extraction v7 change summary

- Migrated from legacy `mer.extractor.analyze` app call to `mer.fmc_router.analyze`.
- Registered 10 FMC issuer modules with safe unknown/ambiguous fallback.
- Added native table-stream parsers for Desjardins, Sun Life, and National Bank Investments.
- Corrected RBC/NBI title handling through source-derived company profiles.
- Added physical fund section representations and PDF region-splitting support.
- Introduced fund/class/row identifiers; correction endpoint now accepts `row_id`.
- Included a new source-verified 12-document acceptance suite and fixtures.
- Included `openpyxl` as a required base dependency.
- Preserved original frontend, SQLite records, re-scan snapshots, PDF viewer and exports.
- Excluded database/history and Python virtualenv from release archive.
- Did not introduce Docling.

Build-time focused result: 26 passed (native extraction + core engine, Excel and SQLite unit checks). Full Windows/Flask/PaddleOCR regression remains for the user.
