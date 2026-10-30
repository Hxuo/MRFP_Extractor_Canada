
"""Regression tests for MER Extraction Excel exports."""

import unittest
from datetime import datetime
from io import BytesIO

from openpyxl import load_workbook

from mer.excel_export import build_excel


class ExcelExportRegressionTests(unittest.TestCase):

    def setUp(self):
        self.document = {
            "filename": "example-mrfp.pdf",
            "verified": True,
            "results": [
                {
                    "fund_name": "Example Canadian Bond Fund",
                    "class_name": "Series A",
                    "year": 2026,
                    "report_date": "2026-06-30",
                    "MER": 1.15,
                    "TER": None,
                    "PTR": 45.75,
                    "evidence": {},
                },
                {
                    "fund_name": "Example Canadian Bond Fund",
                    "class_name": "Series F",
                    "year": 2026,
                    "report_date": None,
                    "MER": 0.65,
                    "TER": 0.02,
                    "PTR": None,
                    "evidence": {},
                },
            ],
        }

        self.workbook = load_workbook(
            build_excel([self.document])
        )

        self.main = self.workbook["Extraction Results"]
        self.lipper = self.workbook["Lipper Format"]

    def test_two_worksheets(self):
        self.assertEqual(
            self.workbook.sheetnames,
            ["Extraction Results", "Lipper Format"],
        )

        self.assertEqual(self.main.max_row, 3)
        self.assertEqual(self.lipper.max_row, 3)

    def test_full_class_names(self):
        self.assertEqual(
            self.main["B2"].value,
            "Example Canadian Bond Fund Series A",
        )
        self.assertEqual(
            self.lipper["B3"].value,
            "Example Canadian Bond Fund Series F",
        )

    def test_numeric_ratios_and_missing_values(self):
        self.assertEqual(self.main["E2"].value, 1.15)
        self.assertEqual(self.main["G2"].value, 45.75)
        self.assertEqual(self.lipper["C3"].value, 0.65)
        self.assertEqual(self.lipper["D3"].value, 0.02)

        self.assertIsNone(self.main["F2"].value)
        self.assertIsNone(self.main["G3"].value)
        self.assertIsNone(self.lipper["D2"].value)
        self.assertIsNone(self.lipper["E3"].value)

    def test_real_excel_dates(self):
        value = self.lipper["F2"].value

        self.assertIsInstance(value, datetime)
        self.assertEqual(
            value.strftime("%m/%d/%Y"),
            "06/30/2026",
        )

        self.assertEqual(
            self.lipper["F2"].number_format,
            "mm/dd/yyyy",
        )

        self.assertIsNone(self.lipper["F3"].value)

    def test_blank_lipper_ids(self):
        self.assertIsNone(self.lipper["A2"].value)
        self.assertIsNone(self.lipper["A3"].value)

    def test_verification_status(self):
        self.assertEqual(
            self.main["L2"].value,
            "Verified",
        )
        self.assertEqual(
            self.main["L3"].value,
            "Verified",
        )

    def test_unknown_document_fields(self):
        legacy = {
            "filename": "legacy.pdf",
            "verified": False,
            "results": [
                {
                    "class_name": "Series A",
                    "year": 2025,
                    "MER": 1.5,
                    "TER": None,
                    "PTR": None,
                }
            ],
        }

        workbook = load_workbook(
            build_excel([legacy])
        )

        main = workbook["Extraction Results"]
        lipper = workbook["Lipper Format"]

        self.assertEqual(main["B2"].value, "Series A")
        self.assertIsNone(main["D2"].value)
        self.assertEqual(main["L2"].value, "Unverified")
        self.assertIsNone(lipper["F2"].value)


if __name__ == "__main__":
    unittest.main()
