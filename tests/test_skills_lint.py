"""Phase 5 — skill file lint tests.

Each skill file must have specific sections; structural quality is checked
because Claude reads these as authoritative rules every cycle. A drifting
skill file is a drifting brain.

These tests act as the executable contract for the oversight skill playbook:
- File presence + required sections (the brain's procedural anatomy)
- 4096-char cap (prompt-cache-friendly chunk size — Anthropic prompt cache TTL
  benefits from stable, small skills)
- No vague language (skills are executable; if Claude has to interpret, the
  skill has failed)
- Cross-reference integrity (oversight-loop must reference every skill it
  loads)
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "crypto-bot" / "claude-routines" / "skills"
ROUTINES_DIR = REPO_ROOT / "crypto-bot" / "claude-routines" / "routines"

REQUIRED_SECTIONS: dict[str, list[str]] = {
    "regime-detection.md": [
        "# Regime Detection",
        "## When to apply",
        "## Decision rules",
        "## Output format",
    ],
    "signal-evaluation.md": [
        "# Signal Evaluation",
        "## When to apply",
        "## Pre-approval checklist",
        "## Decision rules",
    ],
    "trading-discipline.md": [
        "# Trading Discipline (Iron Rules)",
        "## Iron Rules",
        "## Failure modes",
    ],
    "known-traps.md": [
        "# Known Traps",
        "## How this file grows",
        "## Current entries",
    ],
    "post-mortem-protocol.md": [
        "# Post-Mortem Protocol",
        "## Trigger",
        "## Procedure",
        "## Output",
    ],
}

ROUTINE_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "oversight-loop.md": [
        "# Oversight Loop Routine",
        "## Cadence",
        "## Procedure",
        "## API contract",
    ],
}

VAGUE_PHRASES = [
    "be careful",
    "use judgement",
    "use judgment",
    "use common sense",
    "as appropriate",
    "if needed",
    "as you see fit",
]


@pytest.mark.parametrize(
    "filename,sections", list(REQUIRED_SECTIONS.items()),
)
def test_skill_has_required_sections(filename: str, sections: list[str]) -> None:
    path = SKILLS_DIR / filename
    assert path.is_file(), f"{path} missing"
    body = path.read_text(encoding="utf-8")
    missing = [s for s in sections if s not in body]
    assert not missing, f"{filename} missing sections: {missing}"


@pytest.mark.parametrize(
    "filename,sections", list(ROUTINE_REQUIRED_SECTIONS.items()),
)
def test_routine_has_required_sections(filename: str, sections: list[str]) -> None:
    path = ROUTINES_DIR / filename
    assert path.is_file(), f"{path} missing"
    body = path.read_text(encoding="utf-8")
    missing = [s for s in sections if s not in body]
    assert not missing, f"{filename} missing sections: {missing}"


@pytest.mark.parametrize("filename", list(REQUIRED_SECTIONS.keys()))
def test_skill_file_under_4096_chars(filename: str) -> None:
    path = SKILLS_DIR / filename
    body = path.read_text(encoding="utf-8")
    assert len(body) < 4096, (
        f"{filename} too long ({len(body)} chars; cap 4096 for prompt-cache "
        f"friendliness — split into a sibling skill if more rules are needed)."
    )


@pytest.mark.parametrize("filename", list(REQUIRED_SECTIONS.keys()))
def test_skill_no_vague_language(filename: str) -> None:
    path = SKILLS_DIR / filename
    body = path.read_text(encoding="utf-8").lower()
    found = [p for p in VAGUE_PHRASES if p in body]
    assert not found, (
        f"{filename} contains vague language: {found}. Skills must be "
        f"executable, not interpretive — replace with concrete numeric or "
        f"boolean criteria."
    )


def test_oversight_loop_references_all_skills() -> None:
    routine = (ROUTINES_DIR / "oversight-loop.md").read_text(encoding="utf-8")
    for skill in REQUIRED_SECTIONS.keys():
        assert skill in routine, (
            f"oversight-loop.md must reference {skill} so future operators "
            f"can audit which skills the cron loads."
        )


def test_oversight_loop_documents_decide_endpoint() -> None:
    """Sanity: API contract section must point at /v1/decide and context_bundle.

    These two endpoints are the only brain<->bridge surface the routine touches
    in Phase 5. If either string drifts the routine has lost its API contract.
    """
    routine = (ROUTINES_DIR / "oversight-loop.md").read_text(encoding="utf-8")
    assert "/v1/decide" in routine, "oversight-loop.md missing /v1/decide endpoint"
    assert "/v1/context_bundle" in routine, (
        "oversight-loop.md missing /v1/context_bundle endpoint"
    )
