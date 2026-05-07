"""Phase J of multi-bot restructure plan: compile_refs.py + compiled decision
refs hard-fail on >8K token budget.

Per ADR-002, the compiled file is the per-cycle inject target via
--append-system-prompt-file. Token budget exceedance = silent reasoning
blind spot under prompt cache; script MUST hard-fail with exit code 1
when budget breached.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
COMPILE_SCRIPT = REPO_ROOT / "infra" / "scripts" / "compile_refs.py"

TOKEN_BUDGET = 8000


def _tiktoken_count(text: str) -> int:
    """Count GPT-4 tokens (good-enough proxy for Claude tokens, off by <=10%)."""
    tiktoken = pytest.importorskip("tiktoken")
    enc = tiktoken.encoding_for_model("gpt-4")
    return len(enc.encode(text))


def test_compile_refs_script_exists() -> None:
    assert COMPILE_SCRIPT.is_file(), f"{COMPILE_SCRIPT.relative_to(REPO_ROOT)} missing"


@pytest.mark.parametrize("bot_name", ["crypto", "polymarket"])
def test_compile_refs_runs_for_bot(bot_name: str) -> None:
    """Running compile_refs.py --bot <bot> must succeed (exit 0) and produce
    references/<bot>/compiled/refs-<bot>-decision.md."""
    result = subprocess.run(
        [sys.executable, str(COMPILE_SCRIPT), "--bot", bot_name],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"compile_refs.py --bot {bot_name} failed (exit {result.returncode}). "
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    output_path = REPO_ROOT / "references" / bot_name / "compiled" / f"refs-{bot_name}-decision.md"
    assert output_path.is_file(), (
        f"{output_path.relative_to(REPO_ROOT)} not created"
    )


@pytest.mark.parametrize("bot_name", ["crypto", "polymarket"])
def test_compiled_refs_under_token_budget(bot_name: str) -> None:
    """Compiled file must be <= TOKEN_BUDGET tokens (8K)."""
    output_path = REPO_ROOT / "references" / bot_name / "compiled" / f"refs-{bot_name}-decision.md"
    assert output_path.is_file(), f"{output_path.relative_to(REPO_ROOT)} missing"
    body = output_path.read_text(encoding="utf-8")
    token_count = _tiktoken_count(body)
    assert token_count <= TOKEN_BUDGET, (
        f"{output_path.relative_to(REPO_ROOT)} = {token_count} tokens, "
        f"exceeds budget {TOKEN_BUDGET}"
    )


@pytest.mark.parametrize("bot_name", ["crypto", "polymarket"])
def test_compiled_refs_contains_iron_laws(bot_name: str) -> None:
    """Compiled file MUST include Iron Laws verbatim from global-trading-config.md."""
    output_path = REPO_ROOT / "references" / bot_name / "compiled" / f"refs-{bot_name}-decision.md"
    body = output_path.read_text(encoding="utf-8")
    # All 5 Iron Laws must be present (markers from global-trading-config.md):
    required_law_markers = [
        "Iron Law 1",
        "Iron Law 2",
        "Iron Law 3",
        "Iron Law 4",
        "Iron Law 5",
    ]
    missing = [m for m in required_law_markers if m not in body]
    assert not missing, f"Compiled refs for {bot_name} missing Iron Law markers: {missing}"


@pytest.mark.parametrize("bot_name", ["crypto", "polymarket"])
def test_compiled_refs_contains_quick_heuristics(bot_name: str) -> None:
    """Compiled file MUST include Quick Decision Heuristics from each bot-specific
    reference. Selection rule per ADR-002 + Phase J spec."""
    output_path = REPO_ROOT / "references" / bot_name / "compiled" / f"refs-{bot_name}-decision.md"
    body = output_path.read_text(encoding="utf-8")
    # Marker that the script preserved the Quick Heuristics sections:
    assert "Quick Decision Heuristics" in body, (
        f"Compiled refs for {bot_name} missing 'Quick Decision Heuristics' content"
    )
    # Compiled file MUST drop >= 30% of source character count (deliberate
    # selection, not naive concat — anti-placeholder rule per plan).
    bot_dir = REPO_ROOT / "references" / bot_name
    shared_dir = REPO_ROOT / "references" / "shared"
    global_cfg = REPO_ROOT / "references" / "global-trading-config.md"
    source_total = sum(
        f.read_text(encoding="utf-8").__len__()
        for f in [global_cfg]
        + sorted(bot_dir.glob("*.md"))
        + sorted(shared_dir.glob("*.md"))
    )
    compiled_size = len(body)
    drop_ratio = 1.0 - (compiled_size / source_total)
    assert drop_ratio >= 0.30, (
        f"Compiled refs for {bot_name}: only {drop_ratio:.1%} content drop "
        f"(source={source_total} chars, compiled={compiled_size} chars). "
        f"Need >=30% — script may be doing naive concat instead of selection."
    )


def test_compile_refs_hard_fails_on_oversize_source(tmp_path: Path) -> None:
    """If a source reference were oversized, compile_refs.py must exit 1.
    This test creates a temporary fake reference root, runs the script with a
    --refs-root override, and asserts non-zero exit."""
    # Build a fake refs structure with an OVERSIZED bot-specific file.
    fake_root = tmp_path / "references"
    (fake_root / "crypto" / "compiled").mkdir(parents=True)
    (fake_root / "shared").mkdir(parents=True)
    # global-trading-config.md (real content from repo)
    real_global = (REPO_ROOT / "references" / "global-trading-config.md").read_text(encoding="utf-8")
    (fake_root / "global-trading-config.md").write_text(real_global, encoding="utf-8")
    # Oversized crypto reference (forces compile to exceed budget)
    huge = "## Topic 1 — huge\n" + "## Quick Decision Heuristics\n" + ("- " + "x" * 200 + "\n") * 500
    (fake_root / "crypto" / "huge.md").write_text(huge, encoding="utf-8")
    # Empty shared so source set is small but the bot file is huge
    (fake_root / "shared" / ".gitkeep").touch()
    result = subprocess.run(
        [
            sys.executable,
            str(COMPILE_SCRIPT),
            "--bot",
            "crypto",
            "--refs-root",
            str(fake_root),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 1, (
        f"compile_refs.py should hard-fail with exit 1 on oversize source "
        f"but returned {result.returncode}. stderr:\n{result.stderr}"
    )
    assert "token" in (result.stderr + result.stdout).lower(), (
        "Hard-fail message should mention token budget for operator clarity"
    )
