# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] — 2026-10-20

### Added

- **Real CI test gate.** The workflow ran `pytest -q || echo "No tests yet"`,
  which executes no tests and always exits zero. It is replaced with a
  pinned `pytest==8.3.3` installation and an unconditional `pytest -q`.
  The suite has 74 passing tests and one legitimate skip.
- **Dependency pin guard** (`scripts/pin_guard.py`), wired as a required
  `pin-check` status check.
- **Initial release.** FastAPI REST wrapper around the Corp Recon Engine,
  with a browser GUI offering upload, session tracking and PDF/CSV export.

### Fixed

- **Missing runtime dependencies.** `gradio`, `pandas`, `fpdf2`,
  `pytesseract` and `pymupdf` were used by the code but absent from the
  manifest, so the backend could not start from a clean install.
- **Launcher scripts are location-independent.**

### Changed

- The Ruff rule set is pinned to `E4,E7,E9,F` with `ruff==0.17.1`.
- **README author credit** added: Conrad CJ Wilson.

### Security

- Secret scanning and push protection enabled at the repository level.

[2.0.0]: https://github.com/cjps4linux-creator/recon-engine-pro/releases/tag/v2.0.0
