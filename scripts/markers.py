"""Read side of inline-comment markers in a storage body."""
from __future__ import annotations

from typing import Optional, Set

from matcher import Anchor


def refs(body: str) -> Set[str]:
    raise NotImplementedError


def anchor_for(body: str, ref: str, selection: str) -> Optional[Anchor]:
    """None if no marker with ref; text = visible text inside its pieces, or selection when that is empty."""
    raise NotImplementedError
