"""Root pytest conftest.

Adds ``crypto-bot/freqtrade-config`` to ``sys.path`` so tests can import
``strategies.ClaudeOversightStrategy`` directly. Freqtrade itself is
installed via ``pip install -e freqtrade-fork`` and discovered through
normal site-packages.

Why ``crypto-bot/freqtrade-config`` and not ``freqtrade-fork/user_data``:
Freqtrade's own ``.gitignore`` excludes ``user_data/*`` from the submodule's
git, so files there are untracked. We keep our strategy + config in a
parent-repo directory under the bot's folder (``crypto-bot/freqtrade-config``,
moved here per ADR-001) and tell Freqtrade where to find it via
``--strategy-path crypto-bot/freqtrade-config/strategies
--config crypto-bot/freqtrade-config/config.json``.

Also loads the repo-root ``.env`` so integration tests that depend on
``POSTGRES_*`` env vars work in fresh shells without manual sourcing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FREQTRADE_CONFIG = _REPO_ROOT / "crypto-bot" / "freqtrade-config"

if _FREQTRADE_CONFIG.is_dir() and str(_FREQTRADE_CONFIG) not in sys.path:
    sys.path.insert(0, str(_FREQTRADE_CONFIG))

_ENV_PATH = _REPO_ROOT / ".env"
if _ENV_PATH.is_file():
    # Minimal .env loader — avoids adding python-dotenv as a hard dep.
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _stripped = _line.strip()
        if not _stripped or _stripped.startswith("#") or "=" not in _stripped:
            continue
        _k, _v = _stripped.split("=", 1)
        _k = _k.strip()
        _v = _v.strip().strip('"').strip("'")
        # Don't overwrite values already set in the real environment.
        os.environ.setdefault(_k, _v)
