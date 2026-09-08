"""CW-009 machine-verifiable security matrix export.

The matrix document (``docs/evidence/CW009-SECURITY-MATRIX.md``) maps every
acceptance-spec §6 security requirement to concrete test cases.  This suite
keeps that document honest: every ``file.py::test_name`` reference it makes
must exist as a real test function in ``server/tests``.  A renamed or
deleted test therefore breaks the export until the matrix is updated —
the matrix can never silently rot into fiction.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "docs" / "evidence" / "CW009-SECURITY-MATRIX.md"

# `file.py::test_name` — backtick-quoted references inside the matrix.
_REFERENCE = re.compile(r"`([a-zA-Z0-9_]+\.py)::(test_[a-zA-Z0-9_]+)`")


def _matrix_references() -> list[tuple[str, str]]:
    text = MATRIX_PATH.read_text()
    seen: list[tuple[str, str]] = []
    for file_name, test_name in _REFERENCE.findall(text):
        pair = (file_name, test_name)
        if pair not in seen:
            seen.append(pair)
    return seen


def test_matrix_document_exists_and_lists_references() -> None:
    assert MATRIX_PATH.exists(), f"missing security matrix: {MATRIX_PATH}"
    references = _matrix_references()
    # A matrix that stopped referencing concrete tests cannot be audited.
    assert len(references) >= 40, (
        f"security matrix lists only {len(references)} test references; "
        "it must stay the auditable requirement→test export"
    )


def test_every_matrix_reference_is_a_real_test() -> None:
    missing: list[str] = []
    for file_name, test_name in _matrix_references():
        path = Path(__file__).resolve().parent / file_name
        if not path.exists():
            missing.append(f"{file_name}::test (file missing)")
            continue
        if f"def {test_name}(" not in path.read_text():
            missing.append(f"{file_name}::{test_name}")
    assert not missing, "matrix references non-existent tests: " + ", ".join(missing)


def test_matrix_front_matter_marks_verification_contract() -> None:
    text = MATRIX_PATH.read_text()
    assert "机器可核销" in text
    assert "test_cw009_security_matrix_export" in text


def test_matrix_references_the_cw009_gap_closing_tests() -> None:
    """The four S2/S4/S6 gap-closing tests must stay pinned in the matrix."""
    text = MATRIX_PATH.read_text()
    for name in (
        "test_no_sentry_sdk_enters_the_server_runtime",
        "test_customer_code_materials_never_reach_control_csv_exports",
        "test_forged_fingerprint_is_caught_by_pairing_risk_control",
        "test_session_fixation_injection_is_never_adopted",
    ):
        assert name in text, f"matrix lost the gap-closing test {name}"
