"""Mode `finish`: embed images and cards in the published page and restore comment markers."""
from __future__ import annotations

from typing import Dict, Optional, Tuple


def run(page_id: str, md_path: str, before: Optional[int], client) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints."""
    raise NotImplementedError
