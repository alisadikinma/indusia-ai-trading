"""Repo structure baseline test — Phase 0 deliverable.

Asserts that all foundational scaffolding files and directories exist.
This is the first line of defense against an underbuilt repo.
"""
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "relative_path",
    [
        ".gitignore",
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "CLAUDE.md",
    ],
)
def test_required_root_file_exists(relative_path: str) -> None:
    target = REPO_ROOT / relative_path
    assert target.is_file(), f"{relative_path} not found at repo root ({target})"


@pytest.mark.parametrize(
    "relative_dir",
    [
        # Shared infrastructure (mono-repo per ADR-001)
        "pulse-bridge",
        "infra",
        "tests",
        "docs",
        # freqtrade-fork submodule stays at root per ADR-001 (rewrite-cost > benefit)
        "freqtrade-fork",
        # Per-bot folders (ADR-001)
        "crypto-bot",
        "crypto-bot/claude-routines",
        "crypto-bot/freqtrade-config",
    ],
)
def test_required_directory_exists(relative_dir: str) -> None:
    target = REPO_ROOT / relative_dir
    assert target.is_dir(), f"{relative_dir}/ not found at repo root ({target})"


def test_crypto_bot_readme_exists() -> None:
    """crypto-bot/README.md must explain the bot boundary per ADR-001."""
    readme = REPO_ROOT / "crypto-bot" / "README.md"
    assert readme.is_file(), f"crypto-bot/README.md missing ({readme})"
    body = readme.read_text(encoding="utf-8")
    assert len(body) >= 800, (
        f"crypto-bot/README.md too thin ({len(body)} chars, need >=800)"
    )


def test_old_root_paths_no_longer_exist() -> None:
    """After Phase C refactor, root-level claude-routines/ and freqtrade-config/
    must no longer exist — they moved into crypto-bot/."""
    stale_paths = ["claude-routines", "freqtrade-config"]
    found_stale = [p for p in stale_paths if (REPO_ROOT / p).exists()]
    assert not found_stale, (
        f"Phase C refactor incomplete — stale root paths still present: {found_stale}"
    )


# ---------------------------------------------------------------------------
# Polymarket-bot scaffold (Phase D)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "relative_dir",
    [
        "polymarket-bot",
        "polymarket-bot/claude-routines",
        "polymarket-bot/clob-client",
        "polymarket-bot/strategies",
    ],
)
def test_polymarket_bot_skeleton_dirs(relative_dir: str) -> None:
    target = REPO_ROOT / relative_dir
    assert target.is_dir(), f"polymarket-bot scaffold incomplete: {relative_dir}/ not found"


def test_polymarket_bot_readme_exists_with_phase_plan_marker() -> None:
    """polymarket-bot/README.md must explicitly mark itself SKELETON ONLY
    and reference the planned phased implementation (separate plan)."""
    readme = REPO_ROOT / "polymarket-bot" / "README.md"
    assert readme.is_file(), f"polymarket-bot/README.md missing"
    body = readme.read_text(encoding="utf-8")
    assert len(body) >= 1200, (
        f"polymarket-bot/README.md too thin ({len(body)} chars, need >=1200)"
    )
    # Hard markers preventing the skeleton from being mistaken for a finished bot:
    assert "SKELETON ONLY" in body, "polymarket-bot/README.md must contain 'SKELETON ONLY' marker"
    assert "Brier" in body or "calibration" in body, (
        "README must mention Polymarket-specific gates (Brier score / calibration ECE)"
    )


def test_freqtrade_submodule_is_populated() -> None:
    """freqtrade-fork/ must be a populated git submodule, not an empty dir."""
    freqtrade_dir = REPO_ROOT / "freqtrade-fork"
    assert freqtrade_dir.is_dir(), "freqtrade-fork/ missing"
    # A populated freqtrade clone has setup.py and a freqtrade/ package directory.
    assert (freqtrade_dir / "setup.py").is_file() or (
        freqtrade_dir / "pyproject.toml"
    ).is_file(), "freqtrade-fork/ exists but does not look like a freqtrade clone"
    assert (
        freqtrade_dir / "freqtrade"
    ).is_dir(), "freqtrade-fork/freqtrade/ package directory missing"


def test_claude_md_has_mandatory_sections() -> None:
    """CLAUDE.md must contain the 6 mandatory sections per plan Phase 0 step 6."""
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    required_headings = [
        "## Project Goal",
        "## Architecture",
        "## Key Directories",
        "## Anti-Placeholder Rules",
        "## Debugging Checklist",
        "## Iron Laws",
    ]
    missing = [h for h in required_headings if h not in claude_md]
    assert not missing, f"CLAUDE.md missing required sections: {missing}"


def test_gitignore_covers_secrets_and_logs() -> None:
    """.gitignore must protect secrets and avoid committing freqtrade runtime logs."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    required_patterns = [".env", "__pycache__", "*.pyc", "freqtrade-fork/user_data/logs"]
    missing = [p for p in required_patterns if p not in gitignore]
    assert not missing, f".gitignore missing required patterns: {missing}"


# ---------------------------------------------------------------------------
# ADR assertions (Phase A + B of 2026-05-07-multi-bot-references-restructure plan)
# ---------------------------------------------------------------------------

ADR_REQUIRED_MADR_SECTIONS = [
    "## Status",
    "## Context",
    "## Decision",
    "## Consequences",
    "## Alternatives Considered",
    "## References",
]


def test_adr_001_exists_with_madr_sections() -> None:
    """ADR-001 must exist with all 6 MADR sections."""
    adr_path = REPO_ROOT / "docs" / "decisions" / "2026-05-07-001-mono-repo-multi-bot.md"
    assert adr_path.is_file(), f"ADR-001 not found at {adr_path}"
    body = adr_path.read_text(encoding="utf-8")
    missing = [s for s in ADR_REQUIRED_MADR_SECTIONS if s not in body]
    assert not missing, f"ADR-001 missing required MADR sections: {missing}"
    assert len(body) >= 1500, (
        f"ADR-001 too thin ({len(body)} chars, need >=1500) — likely a placeholder"
    )


def test_adr_002_exists_with_madr_sections_and_precedence() -> None:
    """ADR-002 must exist with MADR sections plus the Precedence Order section."""
    adr_path = REPO_ROOT / "docs" / "decisions" / "2026-05-07-002-references-rag-layer.md"
    assert adr_path.is_file(), f"ADR-002 not found at {adr_path}"
    body = adr_path.read_text(encoding="utf-8")
    missing = [s for s in ADR_REQUIRED_MADR_SECTIONS if s not in body]
    assert not missing, f"ADR-002 missing required MADR sections: {missing}"
    assert "## Precedence Order" in body, "ADR-002 must contain '## Precedence Order' section"
    assert len(body) >= 2000, (
        f"ADR-002 too thin ({len(body)} chars, need >=2000) — likely a placeholder"
    )
