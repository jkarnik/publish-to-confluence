"""Mode `comments`: re-anchor a page's inline comments against the markdown file."""
from __future__ import annotations

from typing import Dict, Tuple


def run(page_id: str, md_path: str, client) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints."""
    raise NotImplementedError
