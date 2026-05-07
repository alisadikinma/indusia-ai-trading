"""Phase L of multi-bot restructure plan: routine template asserts.

Per ADR-002, every cron-fired routine for either bot MUST inject the compiled
references file via --append-system-prompt-file. The template at
<bot>/claude-routines/routines/_template.md is the source-of-truth pattern that
future routines (written in Phase 5+) inherit by default.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "bot_name",
    ["crypto", "polymarket"],
)
def test_routine_template_exists(bot_name: str) -> None:
    template = REPO_ROOT / f"{bot_name}-bot" / "claude-routines" / "routines" / "_template.md"
    assert template.is_file(), f"{template.relative_to(REPO_ROOT)} missing"


@pytest.mark.parametrize(
    "bot_name",
    ["crypto", "polymarket"],
)
def test_routine_template_injects_references(bot_name: str) -> None:
    """The template MUST include the --append-system-prompt-file flag pointing
    at the bot's compiled refs file. Future routine authors copy this template
    so the inject convention is preserved by default."""
    template = REPO_ROOT / f"{bot_name}-bot" / "claude-routines" / "routines" / "_template.md"
    body = template.read_text(encoding="utf-8")
    expected_flag = "--append-system-prompt-file"
    expected_path = f"references/{bot_name}/compiled/refs-{bot_name}-decision.md"
    assert expected_flag in body, (
        f"{template.relative_to(REPO_ROOT)} missing --append-system-prompt-file flag"
    )
    assert expected_path in body, (
        f"{template.relative_to(REPO_ROOT)} missing expected refs path: {expected_path}"
    )


@pytest.mark.parametrize(
    "bot_name",
    ["crypto", "polymarket"],
)
def test_routine_template_documents_five_layers(bot_name: str) -> None:
    """Template must document the 5-tier knowledge anatomy so future routine
    authors understand what gets loaded per cycle."""
    template = REPO_ROOT / f"{bot_name}-bot" / "claude-routines" / "routines" / "_template.md"
    body = template.read_text(encoding="utf-8")
    # Must mention all 5 layers + precedence
    required_strings = [
        "Iron Laws",
        "Skill",
        "Memory",
        "Journal",
        "Reference",
        "Precedence",
    ]
    missing = [s for s in required_strings if s not in body]
    assert not missing, (
        f"{template.relative_to(REPO_ROOT)} missing required content: {missing}"
    )
    assert len(body) >= 800, (
        f"{template.relative_to(REPO_ROOT)} too thin ({len(body)} chars, need >=800)"
    )
