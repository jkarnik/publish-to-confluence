"""Link cards: turn web links in a storage body into Confluence cards and back."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Tuple

if TYPE_CHECKING:
    from markdown_doc import LinkRef

CARD_ATTRS = ("data-card-appearance", "data-layout", "data-width")


def make_cards(body: str, links: List[LinkRef]) -> Tuple[str, Dict[str, int]]:
    """Counts {"made", "tagged", "plain", "keptPlainForComment"}."""
    raise NotImplementedError


def unmake_cards(body: str) -> Tuple[str, int]:
    """Turn cards back into plain links; return (body, number unmade)."""
    raise NotImplementedError


def jira_macros_to_links(body: str, view_html: str) -> Tuple[str, int, List[str]]:
    """Return (body, made plain, unresolved keys)."""
    raise NotImplementedError
