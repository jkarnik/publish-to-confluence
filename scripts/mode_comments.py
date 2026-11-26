"""Mode `comments`: re-anchor a page's inline comments against the markdown file."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import visible_text
from markdown_doc import visible_blocks
from markers import anchor_for, refs
from matcher import Anchor, align, find
from textnorm import normalize

OPEN_STATUSES = ("open", "reopened", "dangling")


def _fail(page_id: str, reason: str) -> Tuple[Dict, int]:
    return {"pageId": page_id, "error": reason}, 1


def _http(status: int) -> str:
    return "HTTP %d" % status if status else "network error"


def _anchor(comment: Dict, body: str, present: set) -> Tuple[Optional[Anchor], bool]:
    """(anchor, had_marker); the anchor is None when the comment has nothing to look for."""
    ref = comment.get("ref")
    selection = comment.get("selection") or ""
    if ref and ref in present:
        found = anchor_for(body, ref, selection)
        if found is not None:
            return found, True
    if selection:
        return Anchor(normalize(selection)), False
    return None, False


def _open_entry(comment: Dict, body: str, present: set, texts: List[str],
                old_texts: List[str], alignment: List[Optional[int]]) -> Dict:
    anchor, had_marker = _anchor(comment, body, present)
    entry = {"id": comment.get("id"), "text": anchor.text if anchor else "",
             "status": "staysDetached", "reason": None, "to": None}
    if anchor is None:
        return entry
    result = find(anchor, texts, had_marker, old_texts, alignment)
    if result.status == "exact":
        entry["status"] = "willReattach"
    elif result.status == "moved":
        entry["status"] = "willMove"
        entry["to"] = texts[result.block][result.start:result.end]
    else:
        entry["status"] = "willDetach" if had_marker else "staysDetached"
        entry["reason"] = result.reason
    return entry


def _resolved_entry(comment: Dict, body: str, present: set, texts: List[str],
                    old_texts: List[str], alignment: List[Optional[int]]) -> Dict:
    anchor, _ = _anchor(comment, body, present)
    exact = anchor is not None and find(anchor, texts, False, old_texts, alignment).status == "exact"
    return {"id": comment.get("id"), "text": anchor.text if anchor else "",
            "status": "willReattach" if exact else "notFound"}


def run(page_id: str, md_path: str, client) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints."""
    try:
        with open(md_path, "r", encoding="utf-8") as handle:
            md = handle.read()
    except (OSError, UnicodeDecodeError) as error:
        return _fail(page_id, "could not read %s: %s" % (md_path, error))

    status, page = client.read_page(page_id)
    if status != 200 or not isinstance(page, dict):
        return _fail(page_id, "could not read the page (%s)" % _http(status))
    status, comments = client.inline_comments(page_id)
    if status != 200 or not isinstance(comments, list):
        return _fail(page_id, "could not read the page's comments (%s)" % _http(status))

    body = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
    present = refs(body)
    texts = [block.text for block in visible_blocks(md)]
    old_texts = [block.text for block in visible_text.blocks(body)]  # the blocks anchor_for numbers
    alignment = align(old_texts, texts)

    open_entries: List[Dict] = []
    resolved_entries: List[Dict] = []
    for comment in comments:
        state = comment.get("status")
        if state in OPEN_STATUSES:
            open_entries.append(_open_entry(comment, body, present, texts, old_texts, alignment))
        elif state == "resolved":
            resolved_entries.append(_resolved_entry(comment, body, present, texts, old_texts, alignment))
    will_detach = sum(1 for entry in open_entries if entry["status"] == "willDetach")
    return {"pageId": page_id, "open": open_entries, "resolved": resolved_entries,
            "willDetach": will_detach}, 0
