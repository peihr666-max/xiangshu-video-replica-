"""CW-033 evidence-boundary anchor.

CW-001 §5.5 froze W5 CW-033~039 as *GA-trigger* tasks: pre-GA has no real
customer data, no production archive, and no staging environment access, so
any CW-033 evidence file must stay at ``AUTOMATED_VERIFIED`` and must
explicitly list what remains GA-blocked.

This test is a self-guard: if a future contributor (human or agent) rewrites
``docs/evidence/CW033-EVIDENCE.md`` and either drops the GA-blocked list or
upgrades the evidence level to ``STAGING_VERIFIED``/``REAL_CHAIN_VERIFIED``/
``PRODUCTION_GO`` without a matching owner sign-off in ``CW005-DATA-DISPOSITION.md``
§5, this test fails and forces the conversation back to the freeze anchors.

Nothing here validates the *quality* of the drill itself — that stays with
``test_customer_pitr.py`` (structural) and ``test_cw033_pitr_drill_validation.py``
(runtime validation surface).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = REPO_ROOT / "docs" / "evidence" / "CW033-EVIDENCE.md"
TASK_LEDGER_PATH = REPO_ROOT / "docs" / "客户版任务清单-V3.md"
EVIDENCE_LEDGER_PATH = REPO_ROOT / "docs" / "CUSTOMER-TASK-EVIDENCE-V3.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_cw033_evidence_file_exists() -> None:
    """Anchor: the evidence file itself is present under docs/evidence/."""
    assert EVIDENCE_PATH.is_file(), (
        f"CW-033 evidence file missing at {EVIDENCE_PATH}; "
        "per AGENTS.md §5 evidence files live under docs/evidence/"
    )


def test_cw033_evidence_level_is_capped_at_automated_verified() -> None:
    """Pre-GA CW-033 must not claim STAGING/REAL_CHAIN/PRODUCTION evidence."""
    body = _read(EVIDENCE_PATH)

    # The Evidence Level row must state AUTOMATED_VERIFIED.  Both English
    # (T06/T38 style: `**Evidence Level** | ...`) and Chinese (CW-009 style:
    # `证据层级 | ...`) row labels are accepted; the CW-XXX series in this repo
    # has used both, and CW-033 follows the Chinese precedent.
    level_match = re.search(
        r"(?:\*\*Evidence Level\*\*|证据层级)\s*\|\s*([^|\n]+)",
        body,
    )
    assert level_match, "CW033-EVIDENCE.md must have an **Evidence Level** / 证据层级 row"
    level = level_match.group(1)
    assert "AUTOMATED_VERIFIED" in level, (
        f"Evidence Level must include AUTOMATED_VERIFIED; got: {level.strip()!r}"
    )

    # It must NOT claim any higher tier as the current level.  The Evidence
    # Level row itself is already checked above; the line-level scan below
    # catches a stray claim anywhere else in the document.  Narrative lines
    # that discuss what the evidence is *not* (e.g. "若有人把 Evidence Level
    # 改成 STAGING_VERIFIED，绕过 CW-005 §5 签认") are legitimate and must
    # carry a negation / hypothetical / bypass cue.
    higher_tiers = ("STAGING_VERIFIED", "REAL_CHAIN_VERIFIED", "PRODUCTION_GO")
    negation_cues = (
        # English negation / hypothetical frames
        "not ",
        "not-",
        "non-",
        "never",
        "no ",
        "instead",
        "rather",
        "would",
        "if ",
        "when ",
        "before ",
        "blocked",
        "ga-trigger",
        # Chinese negation / bypass / hypothetical frames
        "未",
        "不得",
        "不宣称",
        "不在",
        "不属于",
        "尚未",
        "并非",
        "非",
        "绕过",
        "误升",
        "越级",
        "改成",
        "改为",
        "升到",
        "升级",
        "如果",
        "若",
        "假如",
        "比如",
        "例如",
        "假设",
        "一旦",
        "ga 触发",
        "ga-trigger",
        "触发前",
        "触发条件",
        "冻结",
    )
    for tier in higher_tiers:
        # Find every line mentioning the tier and require a negation nearby.
        for line in body.splitlines():
            if tier not in line:
                continue
            lowered = line.lower()
            assert any(cue in lowered for cue in negation_cues), (
                f"CW033-EVIDENCE.md line claims {tier} without a negation/GA-block cue: {line!r}"
            )


def test_cw033_evidence_names_the_ga_trigger_freeze_anchors() -> None:
    """The freeze decision is only legitimate if it cites its upstream anchors."""
    body = _read(EVIDENCE_PATH)

    # Must cross-reference the two owner-signed freeze documents.
    assert "CW001-RELEASE-BASELINE" in body or "CW-001" in body, (
        "CW033-EVIDENCE.md must cross-reference CW-001 §5.5 GA-trigger freeze"
    )
    assert "CW005-DATA-DISPOSITION" in body or "CW-005" in body, (
        "CW033-EVIDENCE.md must cross-reference CW-005 §7 data-disposition framework"
    )
    # CW-048 owns PITR/RTO/RPO verification — CW-033 must not swallow that scope.
    assert "CW-048" in body, "CW033-EVIDENCE.md must delegate PITR/RTO/RPO verification to CW-048"


def test_cw033_evidence_lists_ga_blocked_items_explicitly() -> None:
    """The 'Untested Items' / GA-blocked list must be present and non-empty."""
    body = _read(EVIDENCE_PATH)

    # Look for the standard §14 field name or its Chinese equivalent.
    has_untested_section = bool(
        re.search(r"\*\*Untested Items\*\*", body) or re.search(r"未测试项", body)
    )
    assert has_untested_section, (
        "CW033-EVIDENCE.md must have an 'Untested Items' / '未测试项' section"
    )

    # The GA-blocked list must mention the concrete artifacts that require
    # staging: pg_ctl, real base backup, WAL archive.  Structural grep only —
    # we do NOT require them to be *executed*, only *named as blocked*.
    for token in ("pg_ctl", "pg_basebackup", "WAL"):
        assert token in body, f"CW033-EVIDENCE.md must list {token} as GA-blocked in untested items"


def test_cw033_evidence_contains_section_14_ledger_record() -> None:
    """AGENTS.md §5 requires every evidence file to embed the §14 template."""
    body = _read(EVIDENCE_PATH)

    assert "Section 14 Ledger Record" in body or "§14" in body, (
        "CW033-EVIDENCE.md must include a §14 Ledger Record section"
    )

    # The §14 template's canonical Chinese field labels — sample a subset that
    # every closed task includes (see T06-EVIDENCE.md as the reference).
    for field in (
        "任务/工作包",
        "Owner / Reviewer",
        "分支 / 基线 SHA",
        "证据层级",
        "未测试项",
    ):
        assert field in body, f"CW033-EVIDENCE.md §14 record is missing field: {field}"


def test_task_ledger_marks_cw033_as_in_progress_with_pre_ga_scope() -> None:
    """The V3 task ledger §18 CW-033 row must be flipped from '[ ]' to '[~]'
    and must state the pre-GA scope plus the GA-trigger condition, matching
    how CW-001/003/004/005/053 framed their frozen-with-progress state."""
    body = _read(TASK_LEDGER_PATH)

    # Locate the §18 CW-033 status row.  The row format is:
    #   | CW-033 | W5 | 复验 | 执行数据与资产快照恢复演练 | <status> |
    match = re.search(
        r"\|\s*CW-033\s*\|\s*W5\s*\|\s*复验\s*\|\s*执行数据与资产快照恢复演练\s*\|\s*([^|\n]+)\|",
        body,
    )
    assert match, (
        "docs/客户版任务清单-V3.md §18 CW-033 row not found or format changed; "
        "if the ledger schema is being edited, update this anchor too"
    )
    status = match.group(1)

    # Must be flipped from '[ ] 待实施与验收' to '[~] ...'.
    assert "[~]" in status, (
        f"CW-033 status must be '[~]' after pre-GA rehearsal; got: {status.strip()!r}"
    )
    assert "AUTOMATED_VERIFIED" in status, (
        f"CW-033 status must declare AUTOMATED_VERIFIED evidence level; got: {status.strip()!r}"
    )
    # Must retain the GA-trigger framing so nobody reads this as fully done.
    assert "GA" in status, (
        f"CW-033 status must retain the GA-trigger condition; got: {status.strip()!r}"
    )
    # Must point at the evidence file.
    assert "CW033-EVIDENCE.md" in status, (
        f"CW-033 status must cite docs/evidence/CW033-EVIDENCE.md; got: {status.strip()!r}"
    )


def test_customer_task_evidence_ledger_registers_cw033() -> None:
    """The customer evidence ledger must carry a CW-033 entry per AGENTS.md §5."""
    body = _read(EVIDENCE_LEDGER_PATH)

    assert re.search(r"^##\s+CW-?033\b", body, re.MULTILINE), (
        "docs/CUSTOMER-TASK-EVIDENCE-V3.md must register a '## CW-033 ...' section"
    )
    # The section must link back to the full evidence file so reviewers do not
    # have to guess where the §14 record lives.
    assert "CW033-EVIDENCE.md" in body, (
        "CW-033 ledger entry must link to docs/evidence/CW033-EVIDENCE.md"
    )
