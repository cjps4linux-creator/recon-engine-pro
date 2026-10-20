<h1 align="center">Recon Engine Pro</h1>

<p align="center"><b>The Corp Recon Engine wrapped in a FastAPI backend and a native desktop window.</b></p>

<p align="center">
  <a href="https://github.com/cjps4linux-creator/recon-engine-pro/actions/workflows/ci.yml"><img src="https://github.com/cjps4linux-creator/recon-engine-pro/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/license-MIT-0a7563" alt="License: MIT">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-8a5800" alt="Platforms">
  <img src="https://img.shields.io/badge/no_account-no_telemetry-0a7563" alt="No account, no telemetry">
</p>

---

## What it does

A REST API and desktop GUI around the reconciliation engine in
[`corp-recon-engine`](https://github.com/cjps4linux-creator/corp-recon-engine).

- **FastAPI backend** — health, upload, reconcile and export endpoints
- **Native window** — `pywebview` front end instead of a browser tab
- **Session tracking** — SQLite-backed, so a reconciliation run can be
  retrieved later by ID
- **Export** — download the CSV and the PDF report for any completed run

## Relationship to corp-recon-engine

This project **does not vendor** the engine. It imports it from a sibling
checkout:

```
Projects/
├── corp-recon-engine/     <- the engine
└── recon-engine-pro/      <- this API/GUI wrapper
```

`backend/main.py` and `launcher.py` both add `../corp-recon-engine` to
`sys.path`. If you move this repo elsewhere, update `CORP_RECON_PATH` in
`backend/main.py` and `CORP_RECON_DIR` in `launcher.py`.

## Requirements

- Python 3.11+
- A sibling checkout of `corp-recon-engine`

## Install

```bash
git clone https://github.com/cjps4linux-creator/corp-recon-engine.git
git clone https://github.com/cjps4linux-creator/recon-engine-pro.git

cd recon-engine-pro
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Run

```bash
python launcher.py
```

## Licence

MIT — see [LICENSE](LICENSE).

---

## Credits

Built by **Conrad CJ Wilson** — [GitHub](https://github.com/cjps4linux-creator) · [LinkedIn](https://linkedin.com/in/conradcjwilson)

`conradcjwilson0@gmail.com`
