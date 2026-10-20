"""
Shared pytest configuration for the Recon Engine Pro backend test-suite.

The suite is deliberately side-effect free so it can run in CI without
touching developer data:

* ``backend/main.py`` is imported exactly once with ``sqlite3.connect`` and
  ``pathlib.Path.mkdir`` patched, so the module-level ``init_db()`` call can
  never write to the project's real ``data/sessions.db`` and importing the
  backend never creates folders inside the repository.
* Every test that needs persistence gets its own SQLite file inside
  pytest's ``tmp_path``.
* Uploaded documents and generated reports are redirected into ``tmp_path``
  too, so the repository's ``uploads/`` and ``outputs/`` folders stay
  untouched.
* The reconciliation engine is imported from the sibling ``corp-recon-engine``
  checkout. When that checkout is missing, the suite *skips* (it does not
  error) - the skip is raised from a fixture rather than at module level,
  because a module-level ``pytest.skip()`` in ``conftest.py`` makes pytest
  exit with code 1, which would turn a missing optional dependency into a
  red CI build.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import warnings
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
CORP_RECON_DIR = REPO_ROOT.parent / "corp-recon-engine"
STUB_DIR = Path(__file__).resolve().parent / "stubs"
PROJECT_DB_PATH = REPO_ROOT / "data" / "sessions.db"
PROJECT_UPLOAD_DIR = REPO_ROOT / "uploads"
PROJECT_OUTPUT_DIR = REPO_ROOT / "outputs"
PROJECT_DATA_DIR = REPO_ROOT / "data"

# ``backend/main.py`` imports the engine as a top-level module, so both the
# backend folder and the sibling checkout have to be importable, and the repo
# root is added so ``import main`` resolves the same way it does when the
# app is started by hand.
#
# When the sibling checkout is absent (CI clones only this repository) the
# bundled stubs under ``tests/stubs`` take its place, so the suite always
# exercises the real backend instead of skipping.
HAS_REAL_ENGINE = (CORP_RECON_DIR / "recon_engine.py").is_file()
_ENGINE_PATH = CORP_RECON_DIR if HAS_REAL_ENGINE else STUB_DIR

for _path in (str(BACKEND_DIR), str(_ENGINE_PATH), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


# --------------------------------------------------------------------------
# Importing backend/main.py without side effects
# --------------------------------------------------------------------------

_SESSION_SCRATCH = Path(tempfile.mkdtemp(prefix="recon-engine-pro-tests-"))
_IMPORTED_DB_PATH = _SESSION_SCRATCH / "sessions.db"

# Folders that ``backend/main.py`` would otherwise create inside the repo.
_REPO_DIR_REDIRECTS = {
    PROJECT_UPLOAD_DIR: _SESSION_SCRATCH / "uploads",
    PROJECT_OUTPUT_DIR: _SESSION_SCRATCH / "outputs",
    PROJECT_DATA_DIR: _SESSION_SCRATCH / "data",
}


def _same_path(left: Path, right: Path) -> bool:
    """Compare two paths, normalising Windows case and separators."""
    try:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))
    except (OSError, ValueError):  # pragma: no cover - defensive
        return False


def _is_project_database(target: object) -> bool:
    """True when ``target`` points at the repository's real sessions.db."""
    if not isinstance(target, (str, bytes, os.PathLike)):
        return False
    try:
        return _same_path(Path(target), PROJECT_DB_PATH)
    except (OSError, ValueError):  # pragma: no cover - defensive
        return False


def _redirected_path(target: Path) -> Path | None:
    """Return the scratch equivalent of a repository folder, if there is one."""
    for repo_dir, scratch_dir in _REPO_DIR_REDIRECTS.items():
        if _same_path(target, repo_dir):
            return scratch_dir
    return None


def _import_backend_main():
    """Import ``backend/main.py`` with its filesystem side effects redirected.

    Returns the module and the paths it configured *before* the redirect.
    """
    real_connect = sqlite3.connect
    real_mkdir = Path.mkdir

    def guarded_connect(target, *args, **kwargs):
        if _is_project_database(target):
            target = str(_IMPORTED_DB_PATH)
        return real_connect(target, *args, **kwargs)

    def guarded_mkdir(self, *args, **kwargs):
        scratch = _redirected_path(self)
        if scratch is not None:
            return real_mkdir(scratch, *args, **kwargs)
        return real_mkdir(self, *args, **kwargs)

    # Force a fresh import so the module body (and its ``init_db()`` call)
    # always runs under the patched ``sqlite3.connect``.
    sys.modules.pop("main", None)

    sqlite3.connect = guarded_connect
    Path.mkdir = guarded_mkdir
    try:
        with warnings.catch_warnings():
            # PyMuPDF's legacy ``fitz`` shim warns on import; not our code.
            warnings.simplefilter("ignore", category=FutureWarning)
            import main as backend_main
    finally:
        sqlite3.connect = real_connect
        Path.mkdir = real_mkdir

    original_paths = {
        "DB_PATH": backend_main.DB_PATH,
        "UPLOAD_DIR": backend_main.UPLOAD_DIR,
        "OUTPUT_DIR": backend_main.OUTPUT_DIR,
        "BASE_DIR": backend_main.BASE_DIR,
    }
    # Point the module at the scratch copy so nothing can reach the real
    # repository database.
    backend_main.DB_PATH = _IMPORTED_DB_PATH
    return backend_main, original_paths


def pytest_configure(config):
    """Silence third-party deprecation noise from the sibling engine."""
    config.addinivalue_line(
        "filterwarnings",
        'ignore:The parameter "ln" is deprecated:DeprecationWarning',
    )


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _backend_import():
    """The imported ``backend/main.py`` module plus its pre-redirect paths."""
    try:
        return _import_backend_main()
    except ImportError as exc:  # pragma: no cover - depends on the local environment
        pytest.skip(f"could not import the reconciliation engine: {exc}")


@pytest.fixture(scope="session")
def main_module(_backend_import):
    """The imported ``backend/main.py`` module.

    When the sibling ``corp-recon-engine`` checkout is present the real
    engine is used; otherwise the bundled stub under ``tests/stubs`` stands
    in for it so the backend is still exercised end to end.
    """
    backend_main, _original_paths = _backend_import
    return backend_main


@pytest.fixture(scope="session")
def project_db_path() -> Path:
    """Absolute path of the repository's real SQLite database."""
    return PROJECT_DB_PATH


@pytest.fixture(scope="session")
def original_paths(_backend_import) -> dict:
    """The paths ``backend/main.py`` configured before the test redirect."""
    _backend_main, original_paths = _backend_import
    return dict(original_paths)


@pytest.fixture
def isolated_db(main_module, tmp_path, monkeypatch) -> Path:
    """Give the test its own SQLite database inside ``tmp_path``."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    main_module.init_db()
    return db_path


@pytest.fixture
def isolated_dirs(main_module, tmp_path, monkeypatch):
    """Redirect uploads/ and outputs/ into ``tmp_path``."""
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    upload_dir.mkdir()
    output_dir.mkdir()
    monkeypatch.setattr(main_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main_module, "OUTPUT_DIR", output_dir)
    return upload_dir, output_dir


@pytest.fixture
def client(main_module):
    """A FastAPI test client that re-raises unhandled server exceptions."""
    pytest.importorskip("httpx", reason="httpx is required by fastapi.testclient")
    from fastapi.testclient import TestClient

    return TestClient(main_module.app)


@pytest.fixture
def soft_client(main_module):
    """A test client that turns unhandled server exceptions into HTTP 500."""
    pytest.importorskip("httpx", reason="httpx is required by fastapi.testclient")
    from fastapi.testclient import TestClient

    return TestClient(main_module.app, raise_server_exceptions=False)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_scratch_dir():
    """Remove the scratch directory used for the redirected import."""
    yield
    shutil.rmtree(_SESSION_SCRATCH, ignore_errors=True)
