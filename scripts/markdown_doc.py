"""Reads a markdown document: title, local images, web links and visible text blocks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from visible_text import Block


@dataclass(frozen=True)
class ImageRef:
    alt: str
    src: str
    path: str
    name: str  # attachment filename (basename of src)


@dataclass(frozen=True)
class LinkRef:
    url: str
    text: str
    tag: Optional[str]  # None | "block" | "embed" | "embed <layout>" | "plain"


def split_title(md: str) -> Tuple[Optional[str], str]:
    """First "# " line outside code fences."""
    raise NotImplementedError


def local_images(md: str, md_dir: str) -> List[ImageRef]:
    """Unique by src, not http(s)/data:."""
    raise NotImplementedError


def web_links(md: str) -> List[LinkRef]:
    """Inline links, <autolinks>, bare URLs; document order; not in code, not images,
    not links wrapping an image."""
    raise NotImplementedError


def visible_blocks(md: str) -> List[Block]:
    """Body without title; markdown syntax stripped; normalized."""
    raise NotImplementedError
