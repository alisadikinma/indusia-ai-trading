"""Phase 7 — FreqAI prediction models for the crypto bot.

Freqtrade discovers user-supplied prediction models via ``freqaimodel`` +
``freqaimodel_path`` keys in ``config.json``. We keep ours under
``crypto-bot/freqtrade-config/freqaimodels/`` (parent-tracked) instead of
``freqtrade-fork/user_data/freqaimodels/`` (gitignored upstream) — same
pattern as the strategy file.
"""
