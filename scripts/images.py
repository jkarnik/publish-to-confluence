"""Images: size, upload when changed, and embed or strip them in a storage body."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from markdown_doc import ImageRef

OUR_MARK = "sha256:"
MAX_WIDTH = 760


def image_size(path: str) -> Optional[Tuple[int, int]]:
    """Return (width, height) of the image file, or None if it can't be read."""
    raise NotImplementedError


def embed_markup(alt: str, name: str, size: Optional[Tuple[int, int]]) -> str:
    """Return the storage markup that embeds attachment `name`."""
    raise NotImplementedError


def notes(client, page_id: str) -> Dict[str, str]:
    """Attachment title -> comment."""
    raise NotImplementedError


def to_placeholders(body: str, names: Set[str]) -> Tuple[str, int]:
    """Replace embeds of the named attachments with placeholders; return (body, count)."""
    raise NotImplementedError


def remove_embeds(body: str, keep: Set[str]) -> Tuple[str, int]:
    """Remove embeds except those named in `keep`; return (body, count removed)."""
    raise NotImplementedError


def upload_changed(client, page_id: str, images: List[ImageRef], existing: Dict[str, str]) -> Dict:
    """Return {"uploaded", "unchanged", "missingLocally", "failed", "ready": {src: size}}."""
    raise NotImplementedError


def embed(body: str, images: List[ImageRef], ready: Dict[str, Optional[Tuple[int, int]]]) -> Tuple[str, Dict]:
    """Counts {"embedded", "alreadyEmbedded", "stripped", "notOnPage"}."""
    raise NotImplementedError
