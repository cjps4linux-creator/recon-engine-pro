"""
Minimal stand-in for ``corp-recon-engine/recon_engine.py``.

This module is **only** used when the sibling ``corp-recon-engine`` checkout
is not available - which is the case in CI, where only the
``recon-engine-pro`` repository is cloned. It implements just enough of the
engine's public contract for ``backend/main.py`` to import and run:

* ``DEFAULT_THRESHOLD``
* ``AMOUNT_TOLERANCE``
* ``process_reconciliation(bank_file, invoice_file, threshold, amount_tolerance)``

The matching logic is deliberately simple and deterministic (exact
description match plus an amount-tolerance check) so that the backend's
behaviour - not the engine's fuzzy-matching quality - is what the test-suite
asserts. When the real engine *is* present it always wins, because
``backend/main.py`` puts the sibling checkout at the front of ``sys.path``.

Only the standard library is used, so importing it is fast and needs none of
the engine's heavier runtime dependencies (pandas, gradio, pymupdf, ...).
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

DEFAULT_THRESHOLD = 75
AMOUNT_TOLERANCE = 0.05  # 5%

COMPANY_NAME = "Recon Engine Pro (stub engine)"

_counter = {"n": 0}


def _next_suffix() -> str:
    _counter["n"] += 1
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_counter['n']}"


def _normalise(text: Any) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _parse_amount(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").replace(",", "").replace("R", "").replace("$", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _read_rows(file_obj) -> List[Dict[str, Any]]:
    """Read a CSV file object into a list of dicts."""
    path = getattr(file_obj, "name", file_obj)
    rows: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows.append(dict(row))
    return rows


def _pick_column(row: Dict[str, Any], candidates: List[str], fallback: Optional[str] = None) -> Optional[str]:
    lowered = {str(key).strip().lower(): key for key in row}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return fallback


def _write_csv_report(results: Dict[str, Any]) -> str:
    path = f"recon_data_{_next_suffix()}.csv"
    fieldnames = [
        "Type",
        "Date",
        "Bank Description",
        "Bank Amount",
        "Invoice Description",
        "Invoice Amount",
        "Match Score",
        "Category",
        "Status",
        "Reason",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for match in results["matched_transactions"]:
            writer.writerow(
                {
                    "Type": "Matched",
                    "Date": match["bank_date"],
                    "Bank Description": match["bank_desc"],
                    "Bank Amount": match["bank_amount"],
                    "Invoice Description": match["inv_desc"],
                    "Invoice Amount": match["inv_amount"],
                    "Match Score": match["match_score"],
                    "Category": match["category"],
                    "Status": match["status"],
                    "Reason": "",
                }
            )
        for unmatched in results["unmatched_bank"]:
            writer.writerow(
                {
                    "Type": "Unmatched Bank",
                    "Date": unmatched["bank_date"],
                    "Bank Description": unmatched["bank_desc"],
                    "Bank Amount": unmatched["bank_amount"],
                    "Invoice Description": unmatched["best_inv_match"] or "",
                    "Invoice Amount": unmatched["inv_amount"] if unmatched["inv_amount"] is not None else "",
                    "Match Score": unmatched["score"],
                    "Category": "",
                    "Status": "Unmatched",
                    "Reason": unmatched["reason"],
                }
            )
        for unmatched in results["unmatched_invoices"]:
            writer.writerow(
                {
                    "Type": "Unmatched Invoice",
                    "Date": unmatched["inv_date"],
                    "Bank Description": "",
                    "Bank Amount": "",
                    "Invoice Description": unmatched["inv_desc"],
                    "Invoice Amount": unmatched["inv_amount"],
                    "Match Score": "",
                    "Category": "",
                    "Status": "Unmatched",
                    "Reason": unmatched["status"],
                }
            )
    return path


def _write_pdf_report(results: Dict[str, Any]) -> str:
    """Write a small, valid PDF report next to the CSV report."""
    path = f"recon_report_{_next_suffix()}.pdf"
    summary = results["summary"]
    lines = [
        "Recon Engine Pro - Reconciliation Report (stub engine)",
        f"Generated: {summary['generated_at']}",
        f"Matched: {summary['matched_count']}",
        f"Unmatched (Bank): {summary['unmatched_bank_count']}",
        f"Unmatched (Invoice): {summary['unmatched_inv_count']}",
        f"Match Rate: {summary['match_rate']}%",
    ]
    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        for line in lines:
            pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
        pdf.output(path)
    except Exception:  # pragma: no cover - fpdf2 is a declared dependency
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4\n")
            for line in lines:
                handle.write(f"% {line}\n".encode("utf-8"))
    return path


def process_reconciliation(
    bank_file,
    invoice_file,
    threshold: int = DEFAULT_THRESHOLD,
    amount_tolerance: float = AMOUNT_TOLERANCE,
) -> Dict[str, Any]:
    """Reconcile a bank statement against an invoice list.

    Mirrors the shape of the real engine's return value so that
    ``backend/main.py`` works unchanged.
    """
    results: Dict[str, Any] = {
        "matched_transactions": [],
        "unmatched_bank": [],
        "unmatched_invoices": [],
        "summary": {},
        "csv_file": None,
        "pdf_file": None,
    }

    errors: List[str] = []

    def load(file_obj, file_type: str) -> Optional[List[Dict[str, Any]]]:
        if file_obj is None:
            return None
        path = getattr(file_obj, "name", file_obj)
        if not str(path).lower().endswith(".csv"):
            errors.append(f"{file_type}: Unsupported file format. Use CSV, Excel, or PDF.")
            return None
        try:
            return _read_rows(file_obj)
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"{file_type}: {exc}")
            return None

    bank_rows = load(bank_file, "Bank")
    invoice_rows = load(invoice_file, "Invoice")

    if errors:
        results["summary"]["error"] = "; ".join(errors)
        return results

    if not bank_rows or not invoice_rows:
        results["summary"]["error"] = "Please upload both a Bank Statement and an Invoice file."
        return results

    used_invoices = set()
    for bank_row in bank_rows:
        desc_col = _pick_column(bank_row, ["description", "name", "payee", "details"], None)
        amt_col = _pick_column(bank_row, ["amount", "value", "debit", "credit", "total"], None)
        date_col = _pick_column(bank_row, ["date", "transaction date", "posted date"], None)
        if desc_col is None or amt_col is None:
            continue

        bank_desc = bank_row[desc_col]
        bank_amount = _parse_amount(bank_row[amt_col])
        bank_date = bank_row.get(date_col, "") if date_col else ""

        best_index = -1
        best_score = 0
        for index, invoice_row in enumerate(invoice_rows):
            if index in used_invoices:
                continue
            inv_desc_col = _pick_column(invoice_row, ["description", "vendor", "vendor name", "name"], None)
            inv_amt_col = _pick_column(invoice_row, ["amount", "value", "total", "payable"], None)
            if inv_desc_col is None or inv_amt_col is None:
                continue
            if _normalise(invoice_row[inv_desc_col]) != _normalise(bank_desc):
                continue
            inv_amount = _parse_amount(invoice_row[inv_amt_col])
            denominator = max(abs(inv_amount), 0.01)
            if abs(abs(bank_amount) - abs(inv_amount)) / denominator >= amount_tolerance:
                continue
            best_index = index
            best_score = 100
            break

        if best_index == -1:
            results["unmatched_bank"].append(
                {
                    "bank_date": bank_date,
                    "bank_desc": bank_desc,
                    "bank_amount": bank_amount,
                    "best_inv_match": None,
                    "score": 0,
                    "inv_amount": None,
                    "reason": "Low Description Match",
                }
            )
            continue

        invoice_row = invoice_rows[best_index]
        inv_desc_col = _pick_column(invoice_row, ["description", "vendor", "vendor name", "name"], None)
        inv_amt_col = _pick_column(invoice_row, ["amount", "value", "total", "payable"], None)
        inv_date_col = _pick_column(invoice_row, ["date", "invoice date", "due date"], None)
        used_invoices.add(best_index)

        results["matched_transactions"].append(
            {
                "bank_date": bank_date,
                "bank_desc": bank_desc,
                "bank_amount": bank_amount,
                "inv_desc": invoice_row[inv_desc_col],
                "inv_amount": _parse_amount(invoice_row[inv_amt_col]),
                "match_score": best_score,
                "status": "Matched",
                "category": "Other",
                "match_method": "Stub Exact Match",
            }
        )
        results.setdefault("_invoice_dates", {})[best_index] = (
            invoice_row.get(inv_date_col, "") if inv_date_col else ""
        )

    for index, invoice_row in enumerate(invoice_rows):
        if index in used_invoices:
            continue
        inv_desc_col = _pick_column(invoice_row, ["description", "vendor", "vendor name", "name"], None)
        inv_amt_col = _pick_column(invoice_row, ["amount", "value", "total", "payable"], None)
        if inv_desc_col is None or inv_amt_col is None:
            continue
        inv_date_col = _pick_column(invoice_row, ["date", "invoice date", "due date"], None)
        results["unmatched_invoices"].append(
            {
                "inv_date": invoice_row.get(inv_date_col, "") if inv_date_col else "",
                "inv_desc": invoice_row[inv_desc_col],
                "inv_amount": _parse_amount(invoice_row[inv_amt_col]),
                "status": "Unmatched (No Bank Entry)",
            }
        )

    matched_count = len(results["matched_transactions"])
    total_bank = len(bank_rows)
    results["summary"] = {
        "matched_count": matched_count,
        "unmatched_bank_count": len(results["unmatched_bank"]),
        "unmatched_inv_count": len(results["unmatched_invoices"]),
        "total_bank": total_bank,
        "total_invoice": len(invoice_rows),
        "match_rate": round(matched_count / max(total_bank, 1) * 100, 1),
        "pdf_file": None,
        "csv_file": None,
        "threshold_used": threshold,
        "tolerance_used": round(amount_tolerance * 100, 1),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    results.pop("_invoice_dates", None)

    csv_path = _write_csv_report(results)
    results["csv_file"] = csv_path
    results["summary"]["csv_file"] = csv_path

    pdf_path = _write_pdf_report(results)
    results["pdf_file"] = pdf_path
    results["summary"]["pdf_file"] = pdf_path

    return results


def generate_sample_data():
    """Create a tiny sample dataset (mirrors the real engine's helper)."""
    docs_dir = os.path.expanduser("~/Documents/corp-recon-sa-demo-data")
    os.makedirs(docs_dir, exist_ok=True)
    bank_path = os.path.join(docs_dir, "stub_bank_statement.csv")
    invoice_path = os.path.join(docs_dir, "stub_invoices.csv")
    with open(bank_path, "w", encoding="utf-8") as handle:
        handle.write("date,description,amount\n2025-01-02,MTN South Africa,-899.00\n")
    with open(invoice_path, "w", encoding="utf-8") as handle:
        handle.write("date,description,amount\n2025-01-02,MTN South Africa,899.00\n")
    return bank_path, invoice_path
