"""
API and helper tests for the Recon Engine Pro FastAPI backend.

Route paths exercised here were read from ``backend/main.py``:

======================================  ==============================
Method                                  Path
======================================  ==============================
GET                                     ``/api/health``
GET                                     ``/api/config``
GET                                     ``/api/sessions``
GET                                     ``/api/sessions/{session_id}``
DELETE                                  ``/api/sessions/{session_id}``
POST                                    ``/api/reconcile``
GET                                     ``/api/download/csv/{session_id}``
GET                                     ``/api/download/pdf/{session_id}``
======================================  ==============================

The frontend is additionally mounted at ``/app/``.

Every test is pure: no network access, no Gradio import side effects, no
model loads, and no writes to the repository's own database or folders.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

# --------------------------------------------------------------------------
# Sample data used by the reconciliation tests (plain CSV, no fixtures on disk)
# --------------------------------------------------------------------------

BANK_CSV = (
    "date,description,amount\n"
    "2025-01-02,MTN South Africa,-899.00\n"
    "2025-01-03,Vodacom Pty Ltd,-1250.50\n"
    "2025-01-04,Pick n Pay Hyper,-875.80\n"
)

INVOICE_CSV = (
    "date,description,amount\n"
    "2025-01-02,MTN South Africa,899.00\n"
    "2025-01-05,Shell Ultra City,450.00\n"
)


def _write_session(main_module, **overrides):
    """Insert a session row straight through the module's own helper."""
    payload = {
        "session_id": "sess0001",
        "bank_file": "bank.csv",
        "invoice_file": "invoice.csv",
        "threshold": 75,
        "tolerance": 0.05,
        "status": "completed",
        "matched_count": 2,
        "unmatched_bank": 1,
        "unmatched_inv": 1,
        "match_rate": 66.7,
        "csv_path": "outputs/sess0001_report.csv",
        "pdf_path": None,
        "summary": {"matched_count": 2, "match_rate": 66.7},
    }
    payload.update(overrides)
    main_module.save_session(**payload)
    return payload


# ==========================================================================
# Import / wiring
# ==========================================================================


class TestBackendWiring:
    """The backend module must import and expose the expected app object."""

    def test_app_is_a_fastapi_instance(self, main_module):
        from fastapi import FastAPI

        assert isinstance(main_module.app, FastAPI)

    def test_engine_constants_come_from_the_sibling_repo(self, main_module):
        assert main_module.DEFAULT_THRESHOLD == 75
        assert main_module.AMOUNT_TOLERANCE == pytest.approx(0.05)

    def test_configured_paths_point_at_the_repository(self, original_paths):
        """The app is wired to the repository's own data/uploads/outputs."""
        assert original_paths["DB_PATH"].parent.name == "data"
        assert original_paths["DB_PATH"].name == "sessions.db"
        assert original_paths["UPLOAD_DIR"].name == "uploads"
        assert original_paths["OUTPUT_DIR"].name == "outputs"
        assert original_paths["BASE_DIR"].name == "recon-engine-pro"

    @pytest.mark.parametrize(
        ("path", "method"),
        [
            ("/api/health", "GET"),
            ("/api/config", "GET"),
            ("/api/sessions", "GET"),
            ("/api/sessions/{session_id}", "GET"),
            ("/api/sessions/{session_id}", "DELETE"),
            ("/api/reconcile", "POST"),
            ("/api/download/csv/{session_id}", "GET"),
            ("/api/download/pdf/{session_id}", "GET"),
        ],
    )
    def test_expected_routes_are_registered(self, main_module, path, method):
        """Every route the frontend calls must exist with the right verb."""
        registered = {
            (route.path, verb)
            for route in main_module.app.routes
            if hasattr(route, "methods")
            for verb in route.methods
        }
        assert (path, method) in registered

    def test_openapi_schema_lists_the_public_api(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]
        assert "/api/health" in paths
        assert "/api/reconcile" in paths
        assert "/api/config" in paths


# ==========================================================================
# Health & config
# ==========================================================================


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "version": "2.0.0",
            "engine": "corp-recon-engine",
        }

    def test_health_needs_no_database(self, client, project_db_path):
        """``/api/health`` is a pure status probe."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestConfigEndpoint:
    def test_config_exposes_engine_defaults(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200
        body = response.json()
        assert body["default_threshold"] == 75
        # The API reports the tolerance as a percentage, the engine uses a ratio.
        assert body["default_tolerance"] == pytest.approx(5.0)

    def test_config_lists_the_categorisation_buckets(self, client):
        body = client.get("/api/config").json()
        categories = body["categories"]
        assert len(categories) == 13
        assert "Other" in categories
        assert categories[-1] == "Other"
        assert "Telecommunications" in categories

    def test_config_is_stable_across_calls(self, client):
        assert client.get("/api/config").json() == client.get("/api/config").json()


# ==========================================================================
# Session listing / reading
# ==========================================================================


class TestSessionListing:
    def test_empty_database_returns_empty_list(self, client, isolated_db):
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert response.json() == []

    def test_saved_session_appears_in_the_list(self, client, isolated_db, main_module):
        _write_session(main_module=main_module)
        response = client.get("/api/sessions")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == "sess0001"
        assert body[0]["status"] == "completed"
        assert body[0]["match_rate"] == pytest.approx(66.7)

    def test_sessions_are_ordered_newest_first(self, main_module, client, isolated_db, monkeypatch):
        """``get_all_sessions`` orders by ``created_at DESC``."""
        ticks = iter(range(1, 4))

        class _FakeDatetime:
            @classmethod
            def now(cls):
                return datetime(2025, 1, 1, 0, 0, next(ticks))

        monkeypatch.setattr(main_module, "datetime", _FakeDatetime)
        for session_id in ("first", "second", "third"):
            _write_session(main_module=main_module, session_id=session_id)

        body = client.get("/api/sessions").json()
        assert [row["id"] for row in body] == ["third", "second", "first"]

    def test_list_endpoint_returns_pydantic_summaries(self, main_module, client, isolated_db):
        _write_session(main_module=main_module)
        summaries = main_module.get_all_sessions()
        assert len(summaries) == 1
        assert isinstance(summaries[0], main_module.SessionSummary)
        assert summaries[0].id == "sess0001"


class TestSessionDetail:
    def test_unknown_session_returns_404(self, client, isolated_db):
        response = client.get("/api/sessions/does-not-exist")
        assert response.status_code == 404
        assert response.json()["detail"] == "Session not found"

    def test_known_session_returns_the_stored_row(self, main_module, client, isolated_db):
        _write_session(main_module=main_module)
        response = client.get("/api/sessions/sess0001")
        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == "sess0001"
        assert body["bank_file"] == "bank.csv"
        assert body["invoice_file"] == "invoice.csv"
        assert body["threshold"] == 75
        assert body["tolerance"] == pytest.approx(0.05)
        assert body["status"] == "completed"
        assert body["matched_count"] == 2
        assert body["unmatched_bank_count"] == 1
        assert body["unmatched_inv_count"] == 1
        assert body["match_rate"] == pytest.approx(66.7)
        assert body["summary"] == {"matched_count": 2, "match_rate": 66.7}

    def test_created_at_is_an_iso_timestamp(self, main_module, client, isolated_db):
        _write_session(main_module=main_module)
        created_at = client.get("/api/sessions/sess0001").json()["created_at"]
        assert datetime.fromisoformat(created_at).year >= 2025


# ==========================================================================
# Session deletion
# ==========================================================================


class TestSessionDeletion:
    def test_delete_removes_the_row(self, main_module, client, isolated_db):
        _write_session(main_module=main_module)
        response = client.delete("/api/sessions/sess0001")
        assert response.status_code == 200
        assert response.json() == {"status": "deleted"}
        assert client.get("/api/sessions").json() == []

    def test_delete_cleans_up_output_and_upload_files(self, main_module, client, isolated_db, isolated_dirs):
        upload_dir, output_dir = isolated_dirs
        _write_session(main_module=main_module, session_id="del00001")
        (output_dir / "del00001_report.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        (output_dir / "del00001_report.pdf").write_bytes(b"%PDF-1.3")
        (upload_dir / "del00001_bank.csv").write_text("x", encoding="utf-8")
        keeper = output_dir / "unrelated.txt"
        keeper.write_text("keep", encoding="utf-8")

        assert client.delete("/api/sessions/del00001").status_code == 200

        assert not (output_dir / "del00001_report.csv").exists()
        assert not (output_dir / "del00001_report.pdf").exists()
        assert not (upload_dir / "del00001_bank.csv").exists()
        assert keeper.exists()

    def test_deleting_an_unknown_session_is_still_a_200(self, client, isolated_db):
        response = client.delete("/api/sessions/never-existed")
        assert response.status_code == 200
        assert response.json() == {"status": "deleted"}


# ==========================================================================
# Report downloads
# ==========================================================================


class TestDownloads:
    def test_missing_csv_returns_404(self, client, isolated_db, isolated_dirs):
        response = client.get("/api/download/csv/nothing-here")
        assert response.status_code == 404
        assert response.json()["detail"] == "CSV not found"

    def test_missing_pdf_returns_404(self, client, isolated_db, isolated_dirs):
        response = client.get("/api/download/pdf/nothing-here")
        assert response.status_code == 404
        assert response.json()["detail"] == "PDF not found"

    def test_existing_csv_is_served_with_a_filename(self, client, isolated_db, isolated_dirs):
        _, output_dir = isolated_dirs
        (output_dir / "dl000001_report.csv").write_text("Type,Amount\nMatched,10\n", encoding="utf-8")

        response = client.get("/api/download/csv/dl000001")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "recon_dl000001.csv" in response.headers["content-disposition"]
        assert response.text.startswith("Type,Amount")

    def test_existing_pdf_is_served_as_a_pdf(self, client, isolated_db, isolated_dirs):
        _, output_dir = isolated_dirs
        (output_dir / "dl000002_report.pdf").write_bytes(b"%PDF-1.4 fake")

        response = client.get("/api/download/pdf/dl000002")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")


# ==========================================================================
# Reconciliation
# ==========================================================================


class TestReconcile:
    def test_reconcile_requires_both_files(self, client, isolated_db):
        response = client.post("/api/reconcile", data={})
        assert response.status_code == 422

    def test_reconcile_requires_both_files_when_only_one_is_sent(self, client, isolated_db):
        response = client.post(
            "/api/reconcile",
            files={"bank_file": ("bank.csv", BANK_CSV.encode(), "text/csv")},
        )
        assert response.status_code == 422

    def test_reconcile_matches_rows_and_persists_a_session(
        self, client, isolated_db, isolated_dirs, tmp_path, monkeypatch
    ):
        """Full happy path: upload two CSVs, get a session, download the reports."""
        # The engine writes its CSV/PDF relative to the working directory;
        # chdir into tmp_path so nothing lands in the repository.
        monkeypatch.chdir(tmp_path)

        response = client.post(
            "/api/reconcile",
            files={
                "bank_file": ("bank.csv", BANK_CSV.encode(), "text/csv"),
                "invoice_file": ("invoice.csv", INVOICE_CSV.encode(), "text/csv"),
            },
        )
        assert response.status_code == 200
        body = response.json()

        session_id = body["session_id"]
        assert len(session_id) == 8
        assert session_id.isalnum()
        assert body["csv_url"] == f"/api/download/csv/{session_id}"
        assert body["pdf_url"] == f"/api/download/pdf/{session_id}"

        summary = body["summary"]
        assert summary["matched_count"] == 1
        assert summary["total_bank"] == 3
        assert summary["total_invoice"] == 2
        assert summary["match_rate"] == pytest.approx(100 * 1 / 3, abs=0.1)
        assert "error" not in summary

        matched = body["matched"]
        assert len(matched) == 1
        assert matched[0]["bank_desc"] == "MTN South Africa"
        assert matched[0]["inv_desc"] == "MTN South Africa"
        assert matched[0]["status"] == "Matched"

        # The session is persisted and retrievable.
        listed = client.get("/api/sessions").json()
        assert len(listed) == 1
        assert listed[0]["id"] == session_id
        assert listed[0]["status"] == "completed"

        detail = client.get(f"/api/sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["bank_file"] == "bank.csv"

        # Reports were moved into the (redirected) output directory.
        csv_response = client.get(f"/api/download/csv/{session_id}")
        assert csv_response.status_code == 200
        assert "text/csv" in csv_response.headers["content-type"]
        assert "Type,Date" in csv_response.text

        pdf_response = client.get(f"/api/download/pdf/{session_id}")
        assert pdf_response.status_code == 200
        assert pdf_response.content.startswith(b"%PDF")

        # Uploads landed in the (redirected) upload directory.
        upload_dir, output_dir = isolated_dirs
        assert sorted(p.name for p in upload_dir.iterdir()) == [
            f"{session_id}_bank.csv",
            f"{session_id}_invoice.csv",
        ]
        assert (output_dir / f"{session_id}_report.csv").exists()
        assert (output_dir / f"{session_id}_report.pdf").exists()

    def test_unsupported_file_type_is_rejected(self, soft_client, isolated_db, isolated_dirs, tmp_path, monkeypatch):
        """A non CSV/Excel/PDF upload is not silently accepted."""
        monkeypatch.chdir(tmp_path)
        response = soft_client.post(
            "/api/reconcile",
            files={
                "bank_file": ("bank.txt", b"not a spreadsheet", "text/plain"),
                "invoice_file": ("invoice.csv", INVOICE_CSV.encode(), "text/csv"),
            },
        )
        assert response.status_code >= 400


# ==========================================================================
# Module level helpers
# ==========================================================================


class TestSaveSession:
    def test_save_session_writes_a_row(self, main_module, isolated_db):
        _write_session(main_module=main_module)

        conn = sqlite3.connect(isolated_db)
        rows = conn.execute("SELECT id, bank_file, status FROM sessions").fetchall()
        conn.close()
        assert rows == [("sess0001", "bank.csv", "completed")]

    def test_save_session_stores_the_summary_as_json(self, main_module, isolated_db):
        _write_session(main_module=main_module, summary={"matched_count": 7, "nested": {"a": 1}})

        conn = sqlite3.connect(isolated_db)
        raw = conn.execute("SELECT summary FROM sessions WHERE id = ?", ("sess0001",)).fetchone()[0]
        conn.close()
        assert json.loads(raw) == {"matched_count": 7, "nested": {"a": 1}}

    def test_save_session_uses_insert_or_replace(self, main_module, isolated_db):
        """Saving the same id twice must not raise a UNIQUE constraint error."""
        _write_session(main_module=main_module, status="completed")
        _write_session(main_module=main_module, status="failed", matched_count=0)

        conn = sqlite3.connect(isolated_db)
        rows = conn.execute("SELECT id, status, matched_count FROM sessions").fetchall()
        conn.close()
        assert rows == [("sess0001", "failed", 0)]

    def test_save_session_stamps_created_at(self, main_module, isolated_db):
        _write_session(main_module=main_module)

        conn = sqlite3.connect(isolated_db)
        created_at = conn.execute("SELECT created_at FROM sessions").fetchone()[0]
        conn.close()
        assert datetime.fromisoformat(created_at) is not None

    @pytest.mark.parametrize(
        ("match_rate", "matched", "unmatched_bank", "unmatched_inv"),
        [
            (100.0, 10, 0, 0),
            (0.0, 0, 5, 5),
            (66.7, 2, 1, 1),
        ],
    )
    def test_save_session_round_trips_numeric_columns(
        self, main_module, isolated_db, match_rate, matched, unmatched_bank, unmatched_inv
    ):
        _write_session(
            main_module=main_module,
            match_rate=match_rate,
            matched_count=matched,
            unmatched_bank=unmatched_bank,
            unmatched_inv=unmatched_inv,
        )
        summary = main_module.get_all_sessions()[0]
        assert summary.match_rate == pytest.approx(match_rate)
        assert summary.matched_count == matched
        assert summary.unmatched_bank == unmatched_bank
        assert summary.unmatched_inv == unmatched_inv


class TestInitDb:
    def test_init_db_is_idempotent(self, main_module, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        monkeypatch.setattr(main_module, "DB_PATH", db_path)
        main_module.init_db()
        main_module.init_db()

        conn = sqlite3.connect(db_path)
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        columns = [row[1] for row in conn.execute("PRAGMA table_info(sessions)")]
        conn.close()

        assert tables == ["sessions"]
        assert columns == [
            "id",
            "created_at",
            "bank_file",
            "invoice_file",
            "threshold",
            "tolerance",
            "status",
            "matched_count",
            "unmatched_bank",
            "unmatched_inv",
            "match_rate",
            "csv_path",
            "pdf_path",
            "summary",
        ]

    def test_init_db_creates_the_file(self, main_module, tmp_path, monkeypatch):
        db_path = tmp_path / "fresh" / "sessions.db"
        db_path.parent.mkdir()
        monkeypatch.setattr(main_module, "DB_PATH", db_path)
        main_module.init_db()
        assert db_path.exists()


class TestGetAllSessions:
    def test_returns_empty_list_without_rows(self, main_module, isolated_db):
        assert main_module.get_all_sessions() == []

    @pytest.mark.parametrize("count", [1, 3, 7])
    def test_returns_one_summary_per_row(self, main_module, isolated_db, count):
        for index in range(count):
            _write_session(main_module=main_module, session_id=f"sess{index:04d}")

        summaries = main_module.get_all_sessions()
        assert len(summaries) == count
        assert all(isinstance(s, main_module.SessionSummary) for s in summaries)

    def test_nullable_columns_may_be_none(self, main_module, isolated_db):
        _write_session(main_module=main_module, csv_path=None, pdf_path=None)
        summary = main_module.get_all_sessions()[0]
        assert summary.csv_path is None
        assert summary.pdf_path is None


# ==========================================================================
# Pydantic models
# ==========================================================================


class TestReconRequest:
    def test_defaults_match_the_engine(self, main_module):
        request = main_module.ReconRequest()
        assert request.threshold == main_module.DEFAULT_THRESHOLD
        assert request.tolerance == pytest.approx(main_module.AMOUNT_TOLERANCE)
        assert request.profile_name == "default"

    @pytest.mark.parametrize("threshold", [0, 1, 50, 75, 100])
    def test_accepts_valid_thresholds(self, main_module, threshold):
        assert main_module.ReconRequest(threshold=threshold).threshold == threshold

    def test_rejects_a_non_numeric_threshold(self, main_module):
        with pytest.raises(ValidationError):
            main_module.ReconRequest(threshold="not-a-number")

    def test_rejects_a_fractional_threshold(self, main_module):
        with pytest.raises(ValidationError):
            main_module.ReconRequest(threshold=75.5)

    def test_tolerance_may_be_zero(self, main_module):
        assert main_module.ReconRequest(tolerance=0.0).tolerance == 0.0


class TestSessionSummary:
    def _minimal(self, main_module):
        return {
            "id": "abc",
            "created_at": "2025-01-01T00:00:00",
            "bank_file": "b.csv",
            "invoice_file": "i.csv",
            "threshold": 75,
            "tolerance": 0.05,
            "status": "completed",
            "matched_count": 1,
            "unmatched_bank": 0,
            "unmatched_inv": 0,
            "match_rate": 100.0,
            "csv_path": None,
            "pdf_path": None,
        }

    def test_optional_paths_accept_none(self, main_module):
        """``csv_path``/``pdf_path`` are typed ``Optional[str]`` so None is legal."""
        summary = main_module.SessionSummary(**self._minimal(main_module))
        assert summary.csv_path is None
        assert summary.pdf_path is None

    def test_optional_paths_accept_strings(self, main_module):
        payload = self._minimal(main_module)
        payload["csv_path"] = "outputs/abc_report.csv"
        payload["pdf_path"] = "outputs/abc_report.pdf"
        summary = main_module.SessionSummary(**payload)
        assert summary.csv_path == "outputs/abc_report.csv"
        assert summary.pdf_path == "outputs/abc_report.pdf"

    @pytest.mark.parametrize("missing", ["csv_path", "pdf_path"])
    def test_optional_paths_are_still_required(self, main_module, missing):
        """``Optional[str]`` without a default is still a required field."""
        payload = self._minimal(main_module)
        del payload[missing]
        with pytest.raises(ValidationError) as excinfo:
            main_module.SessionSummary(**payload)
        assert excinfo.value.errors()[0]["type"] == "missing"

    @pytest.mark.parametrize("missing", ["id", "status", "match_rate", "threshold"])
    def test_core_fields_are_required(self, main_module, missing):
        payload = self._minimal(main_module)
        del payload[missing]
        with pytest.raises(ValidationError):
            main_module.SessionSummary(**payload)


class TestReorderRequest:
    def test_direction_defaults_to_ascending(self, main_module):
        request = main_module.ReorderRequest(session_id="abc", column="amount")
        assert request.direction == "asc"

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_accepts_supported_directions(self, main_module, direction):
        request = main_module.ReorderRequest(session_id="abc", column="amount", direction=direction)
        assert request.direction == direction

    def test_requires_a_session_id(self, main_module):
        with pytest.raises(ValidationError):
            main_module.ReorderRequest(column="amount")

    def test_requires_a_column(self, main_module):
        with pytest.raises(ValidationError):
            main_module.ReorderRequest(session_id="abc")


# ==========================================================================
# Static frontend mount
# ==========================================================================


class TestFrontendMount:
    def test_app_serves_the_index(self, client):
        response = client.get("/app/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_unknown_api_route_returns_404(self, client):
        assert client.get("/api/does-not-exist").status_code == 404


# ==========================================================================
# Isolation guarantees
# ==========================================================================


class TestIsolation:
    def test_the_project_database_is_never_written(self, client, isolated_db, project_db_path, main_module):
        """Running the suite must not modify the repository's own database."""
        if not project_db_path.exists():
            pytest.skip("no project database present")
        before = project_db_path.read_bytes()
        _write_session(main_module=main_module)
        client.get("/api/sessions")
        client.get("/api/config")
        after = project_db_path.read_bytes()
        assert before == after

    def test_the_scratch_database_is_used_instead(self, main_module, project_db_path):
        assert Path(main_module.DB_PATH) != project_db_path
        assert Path(main_module.DB_PATH).parent != project_db_path.parent
