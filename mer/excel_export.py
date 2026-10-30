
"""Excel workbook generation for MER Extraction v1."""

from datetime import datetime, date
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


MAIN_HEADERS = [
    "Fund Name",
    "Class / Fund",
    "Year",
    "MRFP Date",
    "MER",
    "TER",
    "PTR",
    "MER Source",
    "MER Page",
    "TER Page",
    "PTR Page",
    "Verification",
    "Filename",
]

LIPPER_HEADERS = [
    "Lipper ID",
    "Class / Fund",
    "MER",
    "TER",
    "PTR",
    "MRFP Date (MM/DD/YYYY)",
]


def full_class_name(row):
    """Combine fund and class without duplicating the name."""
    fund = str(row.get("fund_name") or "").strip()
    cls = str(row.get("class_name") or "").strip()

    if not fund:
        return cls

    if not cls or cls.casefold() == fund.casefold():
        return fund

    if cls.casefold().startswith(fund.casefold() + " "):
        return cls

    return f"{fund} {cls}"


def excel_date(value):
    """Convert a valid ISO reporting date to an Excel date."""
    if not value:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def clean_number(value):
    """Preserve missing ratios as blank Excel cells."""
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    import math
    return number if math.isfinite(number) else None


def style_sheet(ws, date_column, numeric_columns):
    """Apply readable headers, filters, and appropriate cell formats."""
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for cell in ws[1]:
        cell.font = Font(
            name="Aptos",
            bold=True,
            color="FFFFFF",
        )
        cell.fill = PatternFill(
            "solid",
            fgColor="24476B",
        )
        cell.alignment = Alignment(
            vertical="center",
            wrap_text=True,
        )

    ws.row_dimensions[1].height = 30

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Aptos", size=10)

        row[date_column - 1].number_format = "mm/dd/yyyy"

        for index in numeric_columns:
            row[index - 1].number_format = "0.00"

    for column in ws.columns:
        letter = get_column_letter(column[0].column)
        max_length = max(
            len(str(cell.value or ""))
            for cell in column
        )

        ws.column_dimensions[letter].width = min(
            max(max_length + 3, 14),
            65,
        )


def build_excel(documents):
    """
    Build a two-sheet XLSX workbook.

    documents: iterable of saved storage.get() dictionaries.
    Corrected/verified values are read from each document.
    """
    wb = Workbook()

    main = wb.active
    main.title = "Extraction Results"

    lipper = wb.create_sheet("Lipper Format")

    main.append(MAIN_HEADERS)
    lipper.append(LIPPER_HEADERS)

    for doc in documents:
        if not doc:
            continue

        verified = (
            "Verified"
            if doc.get("verified")
            else "Unverified"
        )

        filename = Path(
            str(doc.get("filename") or "")
        ).name

        for row in doc.get("results") or []:
            evidence = row.get("evidence") or {}

            name = full_class_name(row)
            report_date = excel_date(
                row.get("report_date")
            )

            main.append([
                row.get("fund_name") or "",
                name,
                row.get("year"),
                report_date,
                clean_number(row.get("MER")),
                clean_number(row.get("TER")),
                clean_number(row.get("PTR")),
                (evidence.get("MER") or {}).get("source", ""),
                (evidence.get("MER") or {}).get("page", ""),
                (evidence.get("TER") or {}).get("page", ""),
                (evidence.get("PTR") or {}).get("page", ""),
                verified,
                filename,
            ])

            lipper.append([
                None,
                name,
                clean_number(row.get("MER")),
                clean_number(row.get("TER")),
                clean_number(row.get("PTR")),
                report_date,
            ])

    style_sheet(
        main,
        date_column=4,
        numeric_columns=(5, 6, 7),
    )

    
    # Plain Lipper Format worksheet:
    # No colored headers, filters, or frozen panes.
    lipper.auto_filter.ref = None
    lipper.freeze_panes = None

    # Retain the required Excel date and numeric formats.
    for row in lipper.iter_rows(min_row=2):
        row[5].number_format = "mm/dd/yyyy"

        for index in (2, 3, 4):
            row[index].number_format = "0.00"


    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
