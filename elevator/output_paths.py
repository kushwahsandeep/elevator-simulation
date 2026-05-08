"""Truncate output CSV paths on each run (no accidental append)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def prepare_requests_journal_csv(path: str) -> str:
    """Prepare path like ``prepare_positions_csv``."""
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        p.unlink()
    logger.info("csv_reset path=%s kind=journey", p)
    return str(p)


def prepare_positions_csv(path: str) -> str:
    """Resolve ``path``, mkdir parents, delete existing file."""
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        p.unlink()
    logger.info("csv_reset path=%s kind=positions", p)
    return str(p)
