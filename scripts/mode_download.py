"""Mode `download`: save one attachment from a page to a local path."""
from __future__ import annotations

from typing import Dict, Tuple


def run(page_id: str, filename: str, dest: str, client) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints."""
    raise NotImplementedError
