"""Mode `prepare`: get a page ready to receive the markdown file."""
from __future__ import annotations

from typing import Dict, Tuple


def run(page_id: str, md_path: str, overwrite: bool, client) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints."""
    raise NotImplementedError
