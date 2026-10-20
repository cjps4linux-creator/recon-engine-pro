"""
Recon Engine Pro - FastAPI Backend
====================================
Wraps the existing corp-recon-engine and exposes a REST API
for the desktop frontend.
"""
import os
import sys
import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add corp-recon-engine to path
CORP_RECON_PATH = Path(__file__).resolve().parent.parent.parent / "corp-recon-engine"
sys.path.insert(0, str(CORP_RECON_PATH))

from recon_engine import process_reconciliation, DEFAULT_THRESHOLD, AMOUNT_TOLERANCE
from pdf_extractor import PDFExtractionError

# ============================================================
# CONFIG
# ============================================================
BASE_DIR = Path(__file__).absolute().parent.parent  # recon-engine-pro/ (no resolve to avoid MSYS path mangling)
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
DB_PATH = BASE_DIR / "data" / "sessions.db"
FRONTEND_DIR = BASE_DIR / "frontend"

for d in [UPLOAD_DIR, OUTPUT_DIR, DB_PATH.parent]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# DATABASE
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT,
            bank_file TEXT,
            invoice_file TEXT,
            threshold INTEGER,
            tolerance REAL,
            status TEXT,
            matched_count INTEGER,
            unmatched_bank INTEGER,
            unmatched_inv INTEGER,
            match_rate REAL,
            csv_path TEXT,
            pdf_path TEXT,
            summary TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ============================================================
# MODELS
# ============================================================
class ReconRequest(BaseModel):
    threshold: int = DEFAULT_THRESHOLD
    tolerance: float = AMOUNT_TOLERANCE
    profile_name: str = "default"

class SessionSummary(BaseModel):
    id: str
    created_at: str
    bank_file: str
    invoice_file: str
    threshold: int
    tolerance: float
    status: str
    matched_count: int
    unmatched_bank: int
    unmatched_inv: int
    match_rate: float
    csv_path: Optional[str]
    pdf_path: Optional[str]

class ReorderRequest(BaseModel):
    session_id: str
    column: str
    direction: str = "asc"

# ============================================================
# APP
# ============================================================
app = FastAPI(title="Recon Engine Pro", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files at /app/
app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# ============================================================
# HELPERS
# ============================================================
def save_session(session_id: str, bank_file: str, invoice_file: str,
                 threshold: int, tolerance: float, status: str,
                 matched_count: int, unmatched_bank: int, unmatched_inv: int,
                 match_rate: float, csv_path: str, pdf_path: str, summary: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO sessions
           (id, created_at, bank_file, invoice_file, threshold, tolerance, status,
            matched_count, unmatched_bank, unmatched_inv, match_rate, csv_path, pdf_path, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, datetime.now().isoformat(), bank_file, invoice_file,
         threshold, tolerance, status, matched_count, unmatched_bank, unmatched_inv,
         match_rate, csv_path, pdf_path, json.dumps(summary))
    )
    conn.commit()
    conn.close()

def get_all_sessions() -> List[SessionSummary]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        results.append(SessionSummary(
            id=row[0], created_at=row[1], bank_file=row[2], invoice_file=row[3],
            threshold=row[4], tolerance=row[5], status=row[6],
            matched_count=row[7], unmatched_bank=row[8], unmatched_inv=row[9],
            match_rate=row[10], csv_path=row[11], pdf_path=row[12]
        ))
    return results

# ============================================================
# ROUTES
# ============================================================

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "engine": "corp-recon-engine"}

@app.post("/api/reconcile")
async def reconcile(
    bank_file: UploadFile = File(...),
    invoice_file: UploadFile = File(...),
    threshold: int = DEFAULT_THRESHOLD,
    tolerance: float = AMOUNT_TOLERANCE
):
    """Run reconciliation on uploaded bank + invoice files."""
    session_id = str(uuid.uuid4())[:8]

    # Save uploads
    bank_path = UPLOAD_DIR / f"{session_id}_{bank_file.filename}"
    inv_path = UPLOAD_DIR / f"{session_id}_{invoice_file.filename}"

    with open(bank_path, "wb") as f:
        f.write(await bank_file.read())
    with open(inv_path, "wb") as f:
        f.write(await invoice_file.read())

    # Run recon engine (synchronous — runs in threadpool by FastAPI)
    try:
        results = process_reconciliation(
            open(bank_path, "rb"),
            open(inv_path, "rb"),
            threshold=threshold,
            amount_tolerance=tolerance
        )
    except PDFExtractionError as e:
        raise HTTPException(400, f"PDF extraction failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"Reconciliation failed: {e}")

    # Move outputs to output dir
    csv_src = Path(results["csv_file"])
    pdf_src = Path(results["pdf_file"])
    csv_dst = OUTPUT_DIR / f"{session_id}_report.csv"
    pdf_dst = OUTPUT_DIR / f"{session_id}_report.pdf"

    if csv_src.exists():
        csv_src.rename(csv_dst)
        results["csv_file"] = str(csv_dst)
    if pdf_src.exists():
        pdf_src.rename(pdf_dst)
        results["pdf_file"] = str(pdf_dst)

    # Save session
    summary = results.get("summary", {})
    save_session(
        session_id=session_id,
        bank_file=bank_file.filename,
        invoice_file=invoice_file.filename,
        threshold=threshold,
        tolerance=tolerance,
        status="completed",
        matched_count=summary.get("matched_count", 0),
        unmatched_bank=summary.get("unmatched_bank_count", 0),
        unmatched_inv=summary.get("unmatched_inv_count", 0),
        match_rate=summary.get("match_rate", 0),
        csv_path=str(csv_dst) if csv_dst.exists() else None,
        pdf_path=str(pdf_dst) if pdf_dst.exists() else None,
        summary=summary
    )

    return {
        "session_id": session_id,
        "summary": summary,
        "matched": results["matched_transactions"],
        "unmatched_bank": results["unmatched_bank"],
        "unmatched_invoices": results["unmatched_invoices"],
        "csv_url": f"/api/download/csv/{session_id}",
        "pdf_url": f"/api/download/pdf/{session_id}",
    }

@app.get("/api/sessions")
async def list_sessions():
    """List all reconciliation sessions."""
    return get_all_sessions()

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a specific session's results."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Session not found")

    # Reconstruct results from stored data
    summary = json.loads(row[13])
    return {
        "session_id": row[0],
        "created_at": row[1],
        "bank_file": row[2],
        "invoice_file": row[3],
        "threshold": row[4],
        "tolerance": row[5],
        "status": row[6],
        "matched_count": row[7],
        "unmatched_bank_count": row[8],
        "unmatched_inv_count": row[9],
        "match_rate": row[10],
        "summary": summary,
    }

@app.get("/api/download/csv/{session_id}")
async def download_csv(session_id: str):
    """Download CSV report for a session."""
    csv_path = OUTPUT_DIR / f"{session_id}_report.csv"
    if not csv_path.exists():
        raise HTTPException(404, "CSV not found")
    return FileResponse(csv_path, filename=f"recon_{session_id}.csv")

@app.get("/api/download/pdf/{session_id}")
async def download_pdf(session_id: str):
    """Download PDF report for a session."""
    pdf_path = OUTPUT_DIR / f"{session_id}_report.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, "PDF not found")
    return FileResponse(pdf_path, filename=f"recon_{session_id}.pdf")

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and its files."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()

    # Clean up files
    for f in OUTPUT_DIR.glob(f"{session_id}_*"):
        f.unlink()
    for f in UPLOAD_DIR.glob(f"{session_id}_*"):
        f.unlink()

    return {"status": "deleted"}

@app.get("/api/config")
async def get_config():
    """Get default configuration."""
    return {
        "default_threshold": DEFAULT_THRESHOLD,
        "default_tolerance": AMOUNT_TOLERANCE * 100,
        "categories": [
            "Professional Services", "Transportation", "Auto & Fuel",
            "Meals & Entertainment", "Cloud & Software", "Subscriptions",
            "Accounting Software", "Telecommunications", "Retail & Supplies",
            "Utilities", "Energy & Fuel", "Banking & Finance", "Other"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8766)
