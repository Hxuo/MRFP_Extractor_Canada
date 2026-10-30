
import unittest
from pathlib import Path
from unittest import result

from mer.extractor import analyze

ROOT = Path(__file__).resolve().parents[1]


def find_pdf(filename):
    locations = [
        ROOT / filename,
        ROOT / "tests" / "fixtures" / filename,
        ROOT / "data" / "pdfs" / filename
    ]

    for path in locations:
        if path.is_file():
            return path

    return None




def _test_history_all():
    """Existing saved-history tests also run against shipped source PDFs."""
    from mer import storage
    from hashlib import sha256
    real = storage.history_all()
    known = {r['filename'] for r in real}
    for name in ("879_EN_MRFP_A.pdf",):
        path = find_pdf(name)
        if path is not None and name not in known:
            real.append({'filename': name, 'hash': sha256(path.read_bytes()).hexdigest()})
    return real


def _test_pdf_path(hash_id):
    from mer import storage
    from hashlib import sha256
    stored = storage.get_pdf_path(hash_id)
    if stored is not None:
        return stored
    for path in (ROOT / "tests" / "fixtures").glob("*.pdf"):
        if sha256(path.read_bytes()).hexdigest() == hash_id:
            return path
    return None

SAMPLES = {
    "2545-samrfp-en-ca.pdf": {
        "fund_name": "FRANKLIN CANADIAN CORE PLUS BOND FUND",
        "rows": [
            ("Series A", 1.21, None, 51.95),
            ("Series F", 0.67, None, 51.95),
            ("Series O", None, None, 51.95),
            ("ETF Series", 0.61, None, 51.95)
        ]
    },
    "mgif-semi2026.pdf": {
        "fund_name": "MIDDLEFIELD GLOBAL INFRASTRUCTURE FUND",
        "rows": [
            ("Series A", 2.73, 0.15, 26.38),
            ("Series F", 1.63, 0.15, 26.38)
        ]
    },
    "H8MK_ENG_MRFP.pdf": {
        "fund_name": "Dynamic Dividend Income Class",
        "rows": [
            ("Series A", 2.19, 0.07, 17.54),
            ("Series F", 1.06, 0.07, 17.54),
            ("Series FT", 1.06, 0.07, 17.54),
            ("Series I", 0.12, 0.07, 17.54),
            ("Series T", 2.16, 0.07, 17.54)
        ]
    },
    "sa-mrfp-xeqt-en-ca.pdf": {
        "fund_name": "iShares Core Equity ETF Portfolio",
        "rows": [
            (
                "iShares Core Equity ETF Portfolio",
                0.19,
                0.02,
                2.30
            )
        ]
    }
}


class ExtractorRegressionTests(unittest.TestCase):

    def test_fund_names_and_ratios(self):
        for filename, expected in SAMPLES.items():
            with self.subTest(pdf=filename):
                path = find_pdf(filename)

                self.assertIsNotNone(
                    path,
                    f"Missing test fixture: {filename}"
                )

                results, diagnostics, raw = analyze(
                    path.read_bytes(),
                    enable_ocr=False
                )

                self.assertTrue(results)

                self.assertEqual(
                    [row.get("fund_name") for row in results],
                    [expected["fund_name"]] * len(results)
                )

                actual = [
                    (
                        row["class_name"],
                        row["MER"],
                        row["TER"],
                        row["PTR"]
                    )
                    for row in results
                ]

                self.assertEqual(actual, expected["rows"])

                for row in results:
                    self.assertEqual(row["year"], 2026)

    def test_reporting_dates_for_validated_layouts(self):
        for filename in (
            "2545-samrfp-en-ca.pdf",
            "mgif-semi2026.pdf",
            "H8MK_ENG_MRFP.pdf"
        ):
            with self.subTest(pdf=filename):
                path = find_pdf(filename)

                self.assertIsNotNone(path)

                results, _, _ = analyze(
                    path.read_bytes(),
                    enable_ocr=False
                )

                for row in results:
                    self.assertEqual(
                        row["report_date"],
                        "2026-06-30"
                    )
                    self.assertFalse(row["needs_review"])

    def test_ishares_date_integration(self):
        path = find_pdf("sa-mrfp-xeqt-en-ca.pdf")
        self.assertIsNotNone(path)

        results, _, _ = analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        self.assertEqual(len(results), 1)

        # Date matching is validated separately but has not
        # yet been integrated into production annotation.
        self.assertEqual(
            results[0]["report_date"],
            "2026-06-30"
        )
        self.assertFalse(results[0]["needs_review"])

        
    def test_class_names_are_valid(self):
        expected_classes = {
            "2545-samrfp-en-ca.pdf": [
                "Series A", "Series F", "Series O", "ETF Series"
            ],
            "mgif-semi2026.pdf": [
                "Series A", "Series F"
            ],
            "H8MK_ENG_MRFP.pdf": [
                "Series A", "Series F", "Series FT",
                "Series I", "Series T"
            ],
            "sa-mrfp-xeqt-en-ca.pdf": [
                "iShares Core Equity ETF Portfolio"
            ]
        }

        for filename, expected in expected_classes.items():
            with self.subTest(pdf=filename):
                path = find_pdf(filename)
                self.assertIsNotNone(path)

                results, _, _ = analyze(
                    path.read_bytes(),
                    enable_ocr=False
                )

                names = [row["class_name"] for row in results]

                self.assertEqual(names, expected)

                for name in names:
                    self.assertNotIn("•", name)
                    self.assertNotIn("Summary of investment", name)

    def test_ishares_fund_is_not_duplicated(self):
        path = find_pdf("sa-mrfp-xeqt-en-ca.pdf")
        self.assertIsNotNone(path)

        results, _, _ = analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        self.assertEqual(len(results), 1)

        row = results[0]

        self.assertEqual(
            row["fund_name"],
            row["class_name"]
        )

        # The UI helper is expected to display this once,
        # not repeat the name twice.
        self.assertEqual(
            row["fund_name"],
            "iShares Core Equity ETF Portfolio"
        )

        
    def test_fund_name_synthetic_layouts(self):
        import pymupdf
        from mer.extractor import detect_fund_name

        scenarios = [
            {
                "name": "Single-line fund title",
                "lines": [
                    "Example Global Equity Fund",
                    "Interim Management Report of Fund Performance"
                ],
                "expected": "Example Global Equity Fund"
            },
            {
                "name": "Multiline fund title",
                "lines": [
                    "EXAMPLE GLOBAL",
                    "INFRASTRUCTURE FUND",
                    "Interim Management Report of Fund Performance"
                ],
                "expected": "EXAMPLE GLOBAL INFRASTRUCTURE FUND"
            },
            {
                "name": "Table of contents rejection",
                "lines": [
                    "Management Discussion of Fund Performance",
                    "This report includes:",
                    "• Management fees",
                    "• Past performance",
                    "• Summary of investment portfolio"
                ],
                "expected": None
            },
            {
                "name": "ETF title with joined words",
                "lines": [
                    "Example Core Equity ETFPortfolio",
                    "For the period ended June 30, 2026"
                ],
                "expected": "Example Core Equity ETF Portfolio"
            },
            {
                "name": "Generic report title only",
                "lines": [
                    "Interim Management Report of Fund Performance",
                    "Financial Highlights",
                    "Management Expense Ratio"
                ],
                "expected": None
            }
        ]

        for scenario in scenarios:
            with self.subTest(layout=scenario["name"]):
                doc = pymupdf.open()
                page = doc.new_page()

                y = 60

                for line in scenario["lines"]:
                    page.insert_text(
                        (50, y),
                        line,
                        fontsize=12
                    )
                    y += 25

                pdf_bytes = doc.tobytes()
                doc.close()

                with pymupdf.open(
                    stream=pdf_bytes,
                    filetype="pdf"
                ) as test_doc:
                    actual = detect_fund_name(test_doc)

                self.assertEqual(
                    actual,
                    scenario["expected"],
                    f"Failed layout: {scenario['name']}"
                )

    def test_two_line_date_header_and_boundaries(self):
        import pymupdf
        from mer.extractor import (
            two_line_table_dates,
            match_two_line_metric_date
        )

        path = find_pdf("sa-mrfp-xeqt-en-ca.pdf")
        self.assertIsNotNone(path)

        pdf_bytes = path.read_bytes()

        results, _, raw = analyze(
            pdf_bytes,
            enable_ocr=False
        )

        with pymupdf.open(
            stream=pdf_bytes,
            filetype="pdf"
        ) as doc:
            page = doc[4]
            headers = two_line_table_dates(page)

            self.assertTrue(any(
                h["date"] == "2026-06-30"
                for h in headers
            ))

            for metric_name, expected_value in (
                ("MER", 0.19),
                ("TER", 0.02),
                ("PTR", 2.30)
            ):
                candidates = [
                    r for r in raw
                    if r["page"] == 5
                    and r["year"] == 2026
                    and r["metric"] == metric_name
                    and r["value"] == expected_value
                ]

                self.assertEqual(len(candidates), 1)

                metric = candidates[0]

                match = match_two_line_metric_date(
                    metric, headers, page
                )

                self.assertIsNotNone(match)
                self.assertEqual(
                    match["date"],
                    "2026-06-30"
                )

                before_section = metric.copy()
                before_section["y"] = 200.0

                self.assertIsNone(
                    match_two_line_metric_date(
                        before_section, headers, page
                    )
                )

                in_footnotes = metric.copy()
                in_footnotes["y"] = 550.0

                self.assertIsNone(
                    match_two_line_metric_date(
                        in_footnotes, headers, page
                    )
                )

                
    def test_spanning_headers_reject_unrelated_evidence(self):
        import pymupdf
        from mer.extractor import spanning_table_dates

        def make_pdf(header_years, footnote, extra_section=False):
            doc = pymupdf.open()
            page = doc.new_page()

            page.insert_text(
                (55, 90),
                "June 30,",
                fontsize=10
            )
            page.insert_text(
                (380, 90),
                "December 31,",
                fontsize=10
            )

            for index, year in enumerate(header_years):
                page.insert_text(
                    (265 + index * 52, 102),
                    str(year),
                    fontsize=10
                )

            page.insert_text(
                (55, 290),
                "Ratios and Supplemental Data",
                fontsize=10
            )

            if extra_section:
                page.insert_text(
                    (55, 365),
                    "Ratios and Supplemental Data",
                    fontsize=10
                )

            page.insert_text(
                (55, 460),
                footnote,
                fontsize=9
            )

            pdf_bytes = doc.tobytes()
            doc.close()
            return pdf_bytes

        scenarios = [
            {
                "name": "No reporting-date footnote",
                "years": [2026, 2025, 2024, 2023],
                "footnote": "Historical performance may vary.",
                "extra": False,
                "should_match": False
            },
            {
                "name": "Explicit historical-date evidence",
                "years": [2026, 2025, 2024, 2023],
                "footnote":
                    "Information is provided as at June 30, 2026 "
                    "and December 31 of the years shown.",
                "extra": False,
                "should_match": True
            },
            {
                "name": "Ambiguous duplicated ratio sections",
                "years": [2026, 2025, 2024, 2023],
                "footnote":
                    "Information is provided as at June 30, 2026 "
                    "and December 31 of the years shown.",
                "extra": True,
                "should_match": False
            }
        ]

        for scenario in scenarios:
            with self.subTest(layout=scenario["name"]):
                data = make_pdf(
                    scenario["years"],
                    scenario["footnote"],
                    scenario["extra"]
                )

                with pymupdf.open(
                    stream=data,
                    filetype="pdf"
                ) as doc:
                    found = spanning_table_dates(doc[0])

                if scenario["should_match"]:
                    self.assertTrue(
                        found,
                        f"Expected date headers: {scenario['name']}"
                    )
                else:
                    self.assertEqual(
                        found,
                        [],
                        f"Unexpected date headers: {scenario['name']}"
                    )

                    
    def test_spanning_dates_reject_unrelated_footnote(self):
        import pymupdf
        from mer.extractor import spanning_table_dates

        def make_pdf(note_position):
            doc = pymupdf.open()
            page = doc.new_page()

            # First table: historical year columns.
            page.insert_text((55, 90), "June 30,", fontsize=10)
            page.insert_text((380, 90), "December 31,", fontsize=10)

            for index, year in enumerate(
                (2026, 2025, 2024, 2023)
            ):
                page.insert_text(
                    (265 + index * 52, 102),
                    str(year),
                    fontsize=10
                )

            page.insert_text(
                (55, 290),
                "Ratios and Supplemental Data",
                fontsize=10
            )

            # A separate non-ratio table starts later.
            page.insert_text(
                (55, 375),
                "Other Financial Information",
                fontsize=10
            )

            page.insert_text(
                (55, note_position),
                "Information is provided as at June 30, 2026 "
                "and December 31 of the years shown.",
                fontsize=9
            )

            pdf_bytes = doc.tobytes()
            doc.close()
            return pdf_bytes

        for note_y, expected_match in (
            (330, True),
            (425, False)
        ):
            with self.subTest(note_y=note_y):
                data = make_pdf(note_y)

                with pymupdf.open(
                    stream=data,
                    filetype="pdf"
                ) as doc:
                    found = spanning_table_dates(doc[0])

                if expected_match:
                    self.assertTrue(
                        found,
                        "Valid nearby footnote was rejected"
                    )
                else:
                    self.assertEqual(
                        found,
                        [],
                        "Unrelated footnote was incorrectly accepted"
                    )

                    
    def test_spanning_historical_dates_and_alignment(self):
        import pymupdf
        from mer.extractor import (
            spanning_table_dates,
            page_items,
            lines
        )

        path = find_pdf("sa-mrfp-xeqt-en-ca.pdf")
        self.assertIsNotNone(path)

        with pymupdf.open(str(path)) as doc:
            page = doc[4]
            date_headers = spanning_table_dates(page)
            rows = lines(page_items(page))

            year_row = next(
                row for row in rows
                if row["text"].strip()
                == "2026 2025 2024 2023 2022 2021"
            )

            positions = {
                int(w.text): w.cx
                for w in year_row["words"]
            }

            expected = {
                2025: "2025-12-31",
                2024: "2024-12-31",
                2023: "2023-12-31",
                2022: "2022-12-31",
                2021: "2021-12-31"
            }

            actual = {
                h["year"]: h["date"]
                for h in date_headers
            }

            self.assertEqual(actual, expected)

            for header in date_headers:
                self.assertAlmostEqual(
                    header["x"],
                    positions[header["year"]],
                    delta=2
                )

            self.assertTrue(all(
                positions[y] > positions[2026]
                for y in expected
            ))

            
    def test_spanning_metric_date_safety(self):
        import pymupdf
        from mer.extractor import (
            spanning_table_dates,
            match_spanning_metric_date,
        )

        path = find_pdf("sa-mrfp-xeqt-en-ca.pdf")
        self.assertIsNotNone(path)

        with pymupdf.open(str(path)) as doc:
            page = doc[4]
            headers = spanning_table_dates(page)

            self.assertEqual(len(headers), 5)

            header = next(
                h for h in headers
                if h["year"] == 2025
            )

            valid = {
                "year": 2025,
                "x": header["x"],
                "y": 380.0,
            }

            # Correct historical column.
            match = match_spanning_metric_date(
                valid, headers, page
            )
            self.assertIsNotNone(match)
            self.assertEqual(
                match["date"], "2025-12-31"
            )

            scenarios = {
                "Wrong reporting year": {
                    **valid,
                    "year": 2020,
                },
                "Wrong horizontal column": {
                    **valid,
                    "x": header["x"] + 100,
                },
                "Before ratio section": {
                    **valid,
                    "y": 200.0,
                },
                "Inside footnote region": {
                    **valid,
                    "y": 550.0,
                },
            }

            for name, candidate in scenarios.items():
                with self.subTest(scenario=name):
                    self.assertIsNone(
                        match_spanning_metric_date(
                            candidate, headers, page
                        ),
                        name,
                    )

            # Duplicated date candidates are ambiguous.
            self.assertIsNone(
                match_spanning_metric_date(
                    valid,
                    headers + [header.copy()],
                    page,
                )
            )

            
    def test_ishares_historical_date_annotation(self):
        from mer.extractor import analyze

        path = find_pdf("sa-mrfp-xeqt-en-ca.pdf")
        self.assertIsNotNone(path)

        results, diagnostics, raw = analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        # Latest selected result must remain unchanged.
        self.assertEqual(len(results), 1)

        latest = results[0]

        self.assertEqual(
            latest["report_date"],
            "2026-06-30"
        )

        self.assertEqual(
            (
                latest["MER"],
                latest["TER"],
                latest["PTR"]
            ),
            (0.19, 0.02, 2.30)
        )

        self.assertFalse(latest["needs_review"])

        # Historical candidates must have correct date/year
        # alignment and recognized metric types.
        historical = [
            r for r in raw
            if r.get("date_source")
            == "spanning-historical-column"
        ]

        self.assertTrue(
            historical,
            "No historical date annotations found"
        )

        for candidate in historical:
            with self.subTest(
                year=candidate["year"],
                metric=candidate["metric"]
            ):
                self.assertEqual(
                    int(candidate["report_date"][:4]),
                    candidate["year"]
                )

                self.assertTrue(
                    candidate["report_date"].endswith("-12-31")
                )

                self.assertIn(
                    candidate["metric"],
                    ("MER", "TER", "PTR")
                )

        # Historical annotation must not replace the latest
        # selected reporting period.
        self.assertGreater(
            latest["report_date"],
            max(r["report_date"] for r in historical)
        )

        
    def test_manulife_fund_name_and_reporting_dates(self):
        from mer import storage
        from mer.extractor import analyze

        target = "879_EN_MRFP_A.pdf"

        saved = next(
            (
                d for d in _test_history_all()
                if d["filename"] == target
            ),
            None
        )

        self.assertIsNotNone(
            saved,
            "Manulife fixture not found in saved history"
        )

        path = _test_pdf_path(saved["hash"])

        self.assertIsNotNone(path)

        results, _, _ = analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        self.assertEqual(len(results), 5)

        self.assertEqual(
            [r["class_name"] for r in results],
            [
                "Advisor Series",
                "Series F",
                "Series FT",
                "Series O",
                "Series T",
            ],
        )

        for row in results:
            with self.subTest(
                class_name=row["class_name"]
            ):
                self.assertEqual(
                    row["fund_name"],
                    "Manulife Climate Action Class"
                )

                self.assertEqual(
                    row["report_date"],
                    "2026-04-30"
                )

                self.assertFalse(
                    row["needs_review"]
                )

        self.assertEqual(
            [
                (r["MER"], r["TER"], r["PTR"])
                for r in results
            ],
            [
                (2.27, 0.09, 26.21),
                (1.14, 0.09, 26.21),
                (1.13, 0.09, 26.21),
                (0.15, 0.09, 26.21),
                (2.29, 0.09, 26.21),
            ],
        )

        
    def test_repeated_header_date_matching_safety(self):
        import pymupdf
        from mer import storage
        from mer.extractor import (
            two_line_table_dates,
            match_repeated_header_metric_date,
        )

        saved = next(
            d for d in _test_history_all()
            if d["filename"] == "879_EN_MRFP_A.pdf"
        )

        path = _test_pdf_path(saved["hash"])

        with pymupdf.open(str(path)) as doc:
            page = doc[10]
            headers = two_line_table_dates(page)

            self.assertGreaterEqual(len(headers), 20)

            first_header = next(
                h for h in headers
                if h["year"] == 2026
            )

            valid = {
                "year": 2026,
                "x": first_header["x"],
                "y": 159.2,
            }

            match = match_repeated_header_metric_date(
                valid, headers, page
            )

            self.assertIsNotNone(match)
            self.assertEqual(
                match["date"],
                "2026-04-30"
            )

            scenarios = {
                "Wrong year": {
                    **valid,
                    "year": 2020,
                },
                "Wrong column": {
                    **valid,
                    "x": 100.0,
                },
                "Before header": {
                    **valid,
                    "y": 90.0,
                },
            }

            for name, metric in scenarios.items():
                with self.subTest(scenario=name):
                    self.assertIsNone(
                        match_repeated_header_metric_date(
                            metric, headers, page
                        ),
                        name,
                    )

            # A duplicate date header must be rejected.
            self.assertIsNone(
                match_repeated_header_metric_date(
                    valid,
                    headers + [first_header.copy()],
                    page,
                )
            )

            
    def test_repeated_header_continuation_page_safety(self):
        import pymupdf
        from mer import storage
        from mer.extractor import (
            analyze,
            two_line_table_dates,
            match_repeated_header_metric_date,
        )

        saved = next(
            d for d in _test_history_all()
            if d["filename"] == "879_EN_MRFP_A.pdf"
        )

        path = _test_pdf_path(saved["hash"])
        self.assertIsNotNone(path)

        _, _, raw = analyze(
            path.read_bytes(),
            enable_ocr=False,
        )

        candidates = [
            r for r in raw
            if r.get("class_name") == "Series T"
            and r.get("year") == 2026
            and r.get("metric") in ("MER", "TER", "PTR")
        ]

        self.assertGreaterEqual(len(candidates), 3)

        with pymupdf.open(str(path)) as doc:
            page = doc[11]
            headers = two_line_table_dates(page)

            matched_metrics = set()

            for candidate in candidates:
                with self.subTest(metric=candidate["metric"]):
                    match = match_repeated_header_metric_date(
                        candidate,
                        headers,
                        page,
                    )

                    self.assertIsNotNone(match)
                    self.assertEqual(
                        match["date"],
                        "2026-04-30",
                    )
                    matched_metrics.add(candidate["metric"])

            self.assertEqual(
                matched_metrics,
                {"MER", "TER", "PTR"},
            )

            # A candidate before the local date header
            # must never inherit its reporting date.
            invalid = candidates[0].copy()
            invalid["y"] = 80.0

            self.assertIsNone(
                match_repeated_header_metric_date(
                    invalid, headers, page
                )
            )

            # A candidate inside the explanatory footnotes
            # must not be assigned a ratio-table date.
            invalid = candidates[0].copy()
            invalid["y"] = 250.0

            self.assertIsNone(
                match_repeated_header_metric_date(
                    invalid, headers, page
                )
            )

            
    def test_purpose_year_only_reporting_dates(self):
        from mer import storage
        from mer.extractor import analyze

        hash_id = (
            "e358e990776c7baa35f5caabbb512674"
            "d959096b835c9c88665d54a7dea393c5"
        )

        path = _test_pdf_path(hash_id)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

        selected, diagnostics, raw = analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        expected = {
            "ETF Units": (0.34, 0.00, 20.85),
            "Class A": (1.40, 0.00, 20.85),
            "Class F": (0.34, 0.00, 20.85),
        }

        self.assertEqual(len(selected), 3)

        by_class = {
            row["class_name"]: row
            for row in selected
        }

        self.assertEqual(
            set(by_class),
            set(expected)
        )

        for class_name, ratios in expected.items():
            with self.subTest(class_name=class_name):
                row = by_class[class_name]

                self.assertEqual(
                    row["fund_name"],
                    "PURPOSE ACTIVE BALANCED FUND"
                )

                self.assertEqual(
                    (
                        row["MER"],
                        row["TER"],
                        row["PTR"],
                    ),
                    ratios
                )

                self.assertEqual(
                    row["year"],
                    2026
                )

                self.assertEqual(
                    row["report_date"],
                    "2026-06-30"
                )

                
    def test_year_only_reporting_date_safety(self):
        import pymupdf

        from mer import storage, extractor

        hash_id = (
            "e358e990776c7baa35f5caabbb512674"
            "d959096b835c9c88665d54a7dea393c5"
        )

        path = _test_pdf_path(hash_id)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

        selected, diagnostics, raw = extractor.analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        with pymupdf.open(str(path)) as doc:
            page = doc[4]
            headers = extractor.local_ratio_year_date_headers(page)

            class_a = next(
                r for r in raw
                if r["class_name"] == "Class A"
                and r["year"] == 2026
                and r["metric"] == "MER"
            )

            valid = extractor.match_year_only_reporting_date(
                class_a, headers, page
            )

            self.assertIsNotNone(valid)
            self.assertEqual(valid["date"], "2026-06-30")

            scenarios = {
                "Wrong year": {
                    **class_a,
                    "year": 2022,
                },
                "Wrong column": {
                    **class_a,
                    "x": 100.0,
                },
                "Before ratio header": {
                    **class_a,
                    "y": 330.0,
                },
                "Inside explanatory footnotes": {
                    **class_a,
                    "y": 500.0,
                },
            }

            for name, candidate in scenarios.items():
                with self.subTest(scenario=name):
                    self.assertIsNone(
                        extractor.match_year_only_reporting_date(
                            candidate,
                            headers,
                            page,
                        ),
                        name,
                    )

            # Duplicate matching headers must be rejected.
            self.assertIsNone(
                extractor.match_year_only_reporting_date(
                    class_a,
                    headers + [valid.copy()],
                    page,
                )
            )

            
    def test_year_only_conflicting_periods_are_rejected(self):
        import pymupdf
        from mer.extractor import year_only_reporting_headers

        doc = pymupdf.open()

        try:
            page = doc.new_page(
                width=612,
                height=792
            )

            page.insert_text(
                (40, 60),
                "Information presented is for the period "
                "January 1, 2026 to June 30, 2026.",
                fontsize=8,
            )

            page.insert_text(
                (40, 80),
                "Information presented is for the period "
                "July 1, 2026 to September 30, 2026.",
                fontsize=8,
            )

            page.insert_text(
                (250, 130),
                "2026 2025 2024",
                fontsize=9,
            )

            page.insert_text(
                (40, 160),
                "Management expense ratio 0.34 0.40 0.45",
                fontsize=9,
            )

            page.insert_text(
                (40, 180),
                "Trading expense ratio 0.00 0.02 0.03",
                fontsize=9,
            )

            page.insert_text(
                (40, 200),
                "Portfolio turnover rate 20.85 39.67 40.35",
                fontsize=9,
            )

            headers = year_only_reporting_headers(page)

            self.assertFalse(
                any(h["year"] == 2026 for h in headers),
                "Conflicting 2026 period-end dates must be rejected."
            )

        finally:
            doc.close()



    def test_year_only_rejects_unrelated_table_date(self):
        import pymupdf

        from mer.extractor import (
            year_only_reporting_headers,
            match_year_only_reporting_date,
        )

        doc = pymupdf.open()

        try:
            page = doc.new_page(width=612, height=792)

            # First ratio table: no reporting-date evidence.
            page.insert_text(
                (40, 55), "First Fund - Ratios",
                fontsize=9,
            )
            page.insert_text(
                (250, 80), "2026 2025 2024",
                fontsize=9,
            )
            page.insert_text(
                (40, 110), "Management expense ratio 1.20",
                fontsize=9,
            )
            page.insert_text(
                (40, 130), "Trading expense ratio 0.10",
                fontsize=9,
            )
            page.insert_text(
                (40, 150), "Portfolio turnover rate 20.00",
                fontsize=9,
            )

            # Separate section.
            page.insert_text(
                (40, 290), "Second Fund - Ratios",
                fontsize=9,
            )
            page.insert_text(
                (250, 320), "2026 2025 2024",
                fontsize=9,
            )
            page.insert_text(
                (40, 350), "Management expense ratio 0.50",
                fontsize=9,
            )
            page.insert_text(
                (40, 370), "Trading expense ratio 0.05",
                fontsize=9,
            )
            page.insert_text(
                (40, 390), "Portfolio turnover rate 10.00",
                fontsize=9,
            )

            page.insert_text(
                (40, 430),
                "Information presented is for the period "
                "January 1, 2026 to June 30, 2026.",
                fontsize=8,
            )

            headers = year_only_reporting_headers(page)

            # Candidate in first table must not inherit
            # the second table's period-end date.
            metric = {
                "year": 2026,
                "x": 265.0,
                "y": 110.0,
            }

            match = match_year_only_reporting_date(
                metric, headers, page
            )

            self.assertIsNone(
                match,
                "First table borrowed a date from another section."
            )

        finally:
            doc.close()

            
    def test_local_ratio_year_date_matching(self):
        import pymupdf
        from mer import storage, extractor

        hash_id = (
            "e358e990776c7baa35f5caabbb512674"
            "d959096b835c9c88665d54a7dea393c5"
        )

        path = _test_pdf_path(hash_id)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

        _, _, raw = extractor.analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        expected = {
            "ETF Units": (4, 476.7),
            "Class A": (5, 193.1),
            "Class F": (5, 477.5),
        }

        with pymupdf.open(str(path)) as doc:
            for class_name, (page_num, expected_x) in expected.items():
                page = doc[page_num - 1]
                headers = extractor.local_ratio_year_date_headers(page)

                candidates = [
                    r for r in raw
                    if r.get("page") == page_num
                    and r.get("class_name") == class_name
                    and r.get("year") == 2026
                    and r.get("metric") in ("MER", "TER", "PTR")
                ]

                self.assertEqual(len(candidates), 3)

                for candidate in candidates:
                    with self.subTest(
                        class_name=class_name,
                        metric=candidate["metric"]
                    ):
                        match = extractor.match_year_only_reporting_date(
                            candidate, headers, page
                        )

                        self.assertIsNotNone(match)
                        self.assertEqual(match["date"], "2026-06-30")
                        self.assertAlmostEqual(
                            match["x"],
                            expected_x,
                            delta=2
                        )

                        
    def test_local_ratio_year_dates_reject_unrelated_notes(self):
        import pymupdf
        from mer.extractor import local_ratio_year_date_headers

        doc = pymupdf.open()

        try:
            page = doc.new_page(width=612, height=792)

            # Ratio table with year-only columns.
            page.insert_text(
                (40, 60),
                "Class A 2026 2025 2024 2023",
                fontsize=9,
            )
            page.insert_text(
                (40, 95),
                "Management expense ratio 1.20",
                fontsize=9,
            )
            page.insert_text(
                (40, 115),
                "Trading expense ratio 0.10",
                fontsize=9,
            )
            page.insert_text(
                (40, 135),
                "Portfolio turnover rate 20.00",
                fontsize=9,
            )

            # Unrelated reporting-period note.
            page.insert_text(
                (40, 220),
                "Information presented is for the period "
                "January 1, 2026 to June 30, 2026.",
                fontsize=8,
            )

            headers = local_ratio_year_date_headers(page)

            self.assertFalse(
                any(h["year"] == 2026 for h in headers),
                "Unrelated notes must not supply ratio dates."
            )

        finally:
            doc.close()

            
    def test_ishares_cbo_current_year_reporting_date(self):
        from mer import storage
        from mer.extractor import analyze

        hash_id = (
            "804df91a914317a896f8623d20dd2620768969bc264a066a512156048884ca3f"
        )

        path = _test_pdf_path(hash_id)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

        selected, diagnostics, raw = analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        self.assertEqual(len(selected), 1)

        result = selected[0]

        self.assertEqual(result["year"], 2025)
        self.assertEqual(result["MER"], 0.27)
        self.assertIsNone(result["TER"])
        self.assertEqual(result["PTR"], 35.93)

        self.assertEqual(
            result["report_date"],
            "2025-12-31"
        )

        # The missing TER must remain missing,
        # not silently converted to zero.
        # Review status is tested separately from date extraction.
# A source-document dash is not a numeric TER value.
        self.assertIsNone(result["TER"])

        
    def test_annual_current_year_date_safety(self):
        import pymupdf
        from mer import extractor

        def make_page(
            annual_heading=True,
            ratio_note=True,
            conflicting_heading=False,
            intervening_section=False,
        ):
            doc = pymupdf.open()
            page = doc.new_page(width=612, height=792)

            if annual_heading:
                page.insert_text(
                    (40, 45),
                    "For the year ended December 31, 2025",
                    fontsize=9,
                )

            if conflicting_heading:
                page.insert_text(
                    (40, 60),
                    "For the year ended December 31, 2024",
                    fontsize=9,
                )

            page.insert_text(
                (300, 100),
                "December 31,",
                fontsize=9,
            )
            page.insert_text(
                (300, 115),
                "2025 2024 2023 2022 2021",
                fontsize=9,
            )
            page.insert_text(
                (40, 180),
                "Ratios and Supplemental Data(f)",
                fontsize=9,
            )
            page.insert_text(
                (40, 205),
                "Management expense ratio 0.27%",
                fontsize=9,
            )

            if intervening_section:
                page.insert_text(
                    (40, 260),
                    "Past Performance",
                    fontsize=9,
                )

            if ratio_note:
                page.insert_text(
                    (40, 300),
                    "(f) This information is provided as at "
                    "December 31 of the years shown.",
                    fontsize=8,
                )

            return doc, page

        cases = (
            ("valid", {}, True),
            ("missing_annual", {"annual_heading": False}, False),
            ("missing_ratio_note", {"ratio_note": False}, False),
            ("conflicting_dates", {"conflicting_heading": True}, False),
            (
                "unrelated_section",
                {"intervening_section": True},
                False,
            ),
        )

        for name, options, should_detect in cases:
            with self.subTest(case=name):
                doc, page = make_page(**options)

                try:
                    matches = (
                        extractor.annual_current_year_ratio_dates(page)
                    )

                    found = any(
                        h["date"] == "2025-12-31"
                        for h in matches
                    )

                    self.assertEqual(
                        found,
                        should_detect,
                        f"Unexpected result for {name}: {matches}"
                    )

                finally:
                    doc.close()

                    
    def test_ishares_cbo_fund_name_spacing(self):
        import pymupdf
        from mer import storage, extractor

        hash_id = (
            "804df91a914317a896f8623d20dd2620768969bc264a066a512156048884ca3f"
        )

        path = _test_pdf_path(hash_id)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

        expected_name = (
            "iShares 1-5 Year Laddered "
            "Corporate Bond Index ETF"
        )

        with pymupdf.open(str(path)) as doc:
            actual_name = extractor.detect_fund_name(doc)

        self.assertEqual(actual_name, expected_name)

        # Also verify that the name propagates correctly
        # to the final extraction results.
        selected, diagnostics, raw = extractor.analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(
            selected[0]["fund_name"],
            expected_name
        )
        self.assertEqual(
            selected[0]["class_name"],
            expected_name
        )

        
    def test_sun_life_granite_conservative_2026(self):
        from pathlib import Path
        from mer.extractor import analyze

        path = (
            Path(__file__).resolve().parent.parent
            / "Sun_Life_Granite_Conservative_Class_MRFP_s.pdf"
        )

        self.assertTrue(path.is_file(), "Sun Life test PDF missing")

        selected, diagnostics, raw = analyze(
            path.read_bytes(),
            enable_ocr=False
        )

        fund_name = "Sun Life Granite Conservative Class"

        expected = {
            "Series A": (1.91, 0.04, 3.58),
            "Series AT5": (1.93, 0.04, 3.58),
            "Series F": (1.02, 0.04, 3.58),
            "Series FT5": (1.02, 0.04, 3.58),
            "Series O": (0.22, 0.04, 3.58),
        }

        self.assertEqual(len(selected), len(expected))

        actual = {row["class_name"]: row for row in selected}

        self.assertEqual(set(actual), set(expected))

        for class_name, (mer, ter, ptr) in expected.items():
            with self.subTest(class_name=class_name):
                row = actual[class_name]

                self.assertEqual(row["fund_name"], fund_name)
                self.assertEqual(row["year"], 2026)
                self.assertEqual(
                    row["report_date"],
                    "2026-06-30"
                )
                self.assertAlmostEqual(row["MER"], mer)
                self.assertAlmostEqual(row["TER"], ter)
                self.assertAlmostEqual(row["PTR"], ptr)

        # Never accept explanatory percentages
        # as actual ratio-table values.
        self.assertFalse(
            any(
                r["metric"] == "PTR"
                and r["value"] in (100.0, 10.0)
                for r in raw
            )
        )















if __name__ == "__main__":
    unittest.main(verbosity=2)
