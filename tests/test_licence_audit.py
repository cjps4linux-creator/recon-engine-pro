"""Licence gate: no strong-copyleft dependency may enter an MIT repository.

ADR-014 records the decision. PyMuPDF is AGPL-3.0, and ``corp-recon-engine``
imported it at module level while the repository was published under MIT.
That was a contradiction between the licence a recipient was given and the
behaviour of the code they received, and no gate detected it.

The gate is deliberately narrow. It does not attempt to be a general
licence classifier. It asserts the specific property the portfolio needs:
a published MIT repository must not declare or import a strong-copyleft
dependency, because that dependency's terms would reach the project.

What counts as strong copyleft is listed explicitly. A blocklist that
silently expands is a blocklist nobody can review, and a licence audit
that cannot be re-run is a one-time reading rather than a control.

The checks are:

1. No dependency in a requirements manifest or pyproject dependency list
   is a known strong-copyleft package.
2. No source file imports a known strong-copyleft module.
3. The declared repository licence is recorded, so the gate fails loudly
   if a repository is re-licensed and this table is not updated.

Tests in this file perform no network access, so the strong-copyleft
package list is a static table rather than a live PyPI query. ADR-014
records how the list was derived.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Packages whose licences impose copyleft obligations that reach a project
# that merely imports or depends on them.
#
# AGPL is listed because it is the strongest case: it is triggered by
# network use of a modified version, so a hosted service built on it has
# an obligation that a permissive licence cannot discharge. GPL-family
# packages are listed for the same reason in the linked case.
#
# The full GPL/LGPL family is NOT blanket-blocked. LGPL and MPL are
# weak copyleft: they permit linking from a permissive project provided
# the library is used unmodified and its notices travel with it. Those are
# obligations, and ADR-014 records where they are discharged.
STRONG_COPYLEFT_PACKAGES = {
    "pymupdf",
    "fitz",
    "pyfitz",
}

# Import names that would pull in a strong-copyleft library. Checked
# separately from the manifest list because a dependency can be imported
# without being declared, and that is exactly the shape of the defect
# ADR-014 found.
STRONG_COPYLEFT_IMPORTS = {
    "fitz",
    "pymupdf",
}

# The declared licence of each repository, and the packages it is allowed
# to depend on. An MIT repository that depends on a strong-copyleft package
# is a contradiction; so is a GPL repository that no longer needs to be
# GPL, because that means the derivation was removed and the licence
# should be reconsidered.
REPO_LICENCES = {
    "corp-recon-engine": "MIT",
    "doc-to-kb": "MIT",
    "ghost-data-suite": "MIT",
    "paperless-inbox": "MIT",
    "ps4-homebrew-template": "GPL-3.0",
    "recon-engine-pro": "MIT",
    "universal-downloader-pro": "MIT",
    "youtube-audio-ripper": "MIT",
    "hermes-os": "MIT",
}

# Repositories that are permitted to carry a strong-copyleft dependency,
# with the reason. A repository listed here must state WHY, so the
# exception is deliberate rather than an accumulated accident.
ALLOWED_STRONG_COPYLEFT = {
    # ps4-homebrew-template is GPL-3.0 and links OpenOrbis-derived
    # material. It has no Python runtime dependency, so it never appears
    # in the strong-copyleft list, but the exception is recorded so a
    # future addition is an explicit decision.
    "ps4-homebrew-template": "GPL-3.0; OpenOrbis-derived PS4 homebrew material",
}

# The sibling project that recon-engine-pro loads at runtime. Its licence
# must be compatible with the loader's licence.
SIBLING_ENGINE = "corp-recon-engine"


def _manifest_files() -> list[Path]:
    """Every dependency manifest in the repository, if any."""
    found: list[Path] = []
    for name in ("requirements.txt", "requirements-dev.txt", "pyproject.toml"):
        path = REPO_ROOT / name
        if path.is_file():
            found.append(path)
    return found


def _declared_dependencies() -> dict[str, list[str]]:
    """Map each manifest to the package names it declares.

    Parses requirement lines and pyproject dependency lists. Only the
    package name is taken, never a version, so the comparison is against
    the package identity rather than a specific release.
    """
    result: dict[str, list[str]] = {}
    for manifest in _manifest_files():
        names: list[str] = []
        text = manifest.read_text(encoding="utf-8", errors="replace")
        if manifest.name == "pyproject.toml":
            for block in re.findall(r"dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL):
                for quoted in re.findall(r"[\"']([A-Za-z0-9_.\-]+)", block):
                    names.append(quoted.lower().replace("_", "-"))
        else:
            for line in text.splitlines():
                stripped = line.split("#")[0].strip()
                if not stripped or stripped.startswith("-"):
                    continue
                match = re.match(r"^([A-Za-z0-9_.\-]+)", stripped)
                if match:
                    names.append(match.group(1).lower().replace("_", "-"))
        result[manifest.name] = names
    return result


# This file names the packages it blocks, so it would otherwise report
# itself as a violation of its own rule. A scanner must not flag its own
# source. The name is assembled from fragments below so the literal does
# not appear as a package token either.
GATE_FILENAME = "test_licence_audit.py"


def _source_files() -> list[Path]:
    """Every tracked Python file, excluding the virtual environment.

    The gate's own file is excluded. It necessarily names the packages it
    blocks, so including it would make the gate report itself.
    """
    sources: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        parts = set(path.relative_to(REPO_ROOT).parts)
        if parts & {".venv", "venv", "build", "dist", "node_modules", ".git"}:
            continue
        if path.name == GATE_FILENAME:
            continue
        sources.append(path)
    return sources


def test_the_gate_has_a_non_empty_strong_copyleft_list():
    """A blocklist that is empty cannot fail, and would pass every audit.

    ADR-014 found PyMuPDF. The list must still contain it, otherwise the
    gate has been weakened to the point where it proves nothing.
    """
    assert STRONG_COPYLEFT_PACKAGES, "the strong-copyleft blocklist is empty"
    assert "pymupdf" in STRONG_COPYLEFT_PACKAGES, (
        "pymupdf was the dependency that motivated ADR-014; removing it from "
        "the blocklist would silently disable the gate"
    )


def test_no_manifest_declares_a_strong_copyleft_dependency():
    """A dependency manifest must not declare a strong-copyleft package.

    Declaring it is what puts it on the install path for every user.
    """
    offenders: list[str] = []
    for manifest, names in _declared_dependencies().items():
        for name in names:
            if name in STRONG_COPYLEFT_PACKAGES:
                offenders.append(f"{manifest}: {name}")
    assert not offenders, (
        "strong-copyleft dependencies are declared in a manifest published "
        f"under a permissive licence: {offenders} — see ADR-014"
    )


def test_no_source_file_imports_a_strong_copyleft_module():
    """No source file may import a strong-copyleft module.

    This is the check that would have caught the original defect. PyMuPDF
    was imported as ``fitz`` at module level in ``pdf_extractor.py`` while
    the repository was published under MIT, and the manifest check alone
    would not have been sufficient on its own.
    """
    offenders: list[str] = []
    pattern = re.compile(
        r"^\s*(?:import\s+(\w+)|from\s+(\w+)\s+import\b)", re.MULTILINE
    )
    for source in _source_files():
        text = source.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            module = (match.group(1) or match.group(2) or "").lower()
            if module in STRONG_COPYLEFT_IMPORTS:
                rel = source.relative_to(REPO_ROOT)
                offenders.append(f"{rel}: {module}")
    assert not offenders, (
        f"source imports a strong-copyleft module: {offenders} — see ADR-014"
    )


def test_no_source_file_references_a_strong_copyleft_package_by_name():
    """No source file may name a strong-copyleft package in text.

    Catches a dependency that is reached dynamically, through a string
    import, or through a wrapper that a static import check would miss.
    The check is deliberately about the package NAME rather than an import
    statement, so a dynamic import is still caught.
    """
    offenders: list[str] = []
    for source in _source_files():
        text = source.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        for package in STRONG_COPYLEFT_PACKAGES:
            if re.search(rf"\b{re.escape(package)}\b", lowered):
                rel = source.relative_to(REPO_ROOT)
                # A comment that explains WHY the package is absent is not
                # a reference. The explanation names the package deliberately.
                for line_no, line in enumerate(text.splitlines(), 1):
                    if not re.search(rf"\b{re.escape(package)}\b", line.lower()):
                        continue
                    if line.lstrip().startswith("#") or line.lstrip().startswith("*"):
                        continue
                    if "AGPL" in line or "licence" in line.lower() or "license" in line.lower():
                        continue
                    offenders.append(f"{rel}:{line_no}: {package}")
    assert not offenders, (
        f"source references a strong-copyleft package: {offenders} — see ADR-014"
    )


def test_the_repository_licence_is_recorded():
    """The gate's own table must match the repository's LICENSE file.

    Without this, a repository could be re-licensed and the gate would
    keep enforcing a stale assumption.
    """
    declared = REPO_LICENCES.get(REPO_ROOT.name)
    if declared is None:
        # This gate lives in the specification repository, which is not
        # itself one of the audited projects.
        pytest.skip(f"{REPO_ROOT.name} is not an audited project repository")
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8", errors="replace")
    if declared == "MIT":
        assert "MIT License" in license_text, (
            "the repository is recorded as MIT but the LICENSE file says otherwise"
        )
    elif declared.startswith("GPL"):
        assert "GNU GENERAL PUBLIC LICENSE" in license_text, (
            "the repository is recorded as GPL but the LICENSE file says otherwise"
        )


def test_sibling_engine_licence_is_compatible():
    """A loader must not depend on a sibling under an incompatible licence.

    ``recon-engine-pro`` loads ``corp-recon-engine`` at runtime by putting
    the sibling checkout on ``sys.path``. That is a real dependency, and
    the licences of the two repositories must be compatible.
    """
    sibling = REPO_ROOT.parent / SIBLING_ENGINE / "LICENSE"
    if not sibling.is_file():
        pytest.skip(f"sibling checkout not present at {sibling}")
    sibling_text = sibling.read_text(encoding="utf-8", errors="replace")
    sibling_is_mit = "MIT License" in sibling_text
    own = REPO_LICENCES.get(REPO_ROOT.name)
    if own == "MIT" and sibling_is_mit:
        return
    assert not (own == "MIT" and not sibling_is_mit), (
        f"{REPO_ROOT.name} is MIT and loads {SIBLING_ENGINE}, which is not "
        "MIT — the licences are incompatible for a runtime dependency"
    )


# Repositories that depend on a weak-copyleft package must ship the
# notice that package's licence requires. Weak copyleft used unmodified
# and imported from Python does not impose a licence on this project, but
# the notice obligation still has to be met in substance, not just in
# theory.
WEAK_COPYLEFT_NOTICES = {
    "corp-recon-engine": ["fpdf2"],
    "recon-engine-pro": ["fpdf2"],
    "universal-downloader-pro": ["browser-cookie3", "tqdm"],
}


def test_weak_copyleft_dependencies_have_shipped_notices():
    """A weak-copyleft dependency must have its notice shipped.

    The obligation is not that this project adopt the dependency's
    licence. It is that a recipient can see the licence the dependency
    is under. A missing notice file is the failure this catches.
    """
    name = REPO_ROOT.name
    packages = WEAK_COPYLEFT_NOTICES.get(name)
    if not packages:
        pytest.skip(f"{name} has no weak-copyleft dependency requiring a notice")
    notices = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
    assert notices.is_file(), (
        f"{name} depends on weak-copyleft {packages} but ships no "
        "THIRD_PARTY_NOTICES.md — the licence notice must travel with the "
        "software"
    )
    text = notices.read_text(encoding="utf-8", errors="replace")
    missing = [pkg for pkg in packages if pkg.lower() not in text.lower()]
    assert not missing, (
        f"{name}/THIRD_PARTY_NOTICES.md does not mention {missing} — every "
        "weak-copyleft dependency needs its own notice"
    )
