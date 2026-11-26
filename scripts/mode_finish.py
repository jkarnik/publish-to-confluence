"""Mode `finish`: embed images and cards in the published page and restore comment markers.

It runs after every text update and makes one minor edit. In order:

1. upload the images whose files changed;
2. embed them (centered, up to 760 px wide, alt text restored) and strip the ones that couldn't upload;
3. re-attach inline comments the text update detached, on the body's visible text, while link
   words are still plain text (a comment on a link's words is wrapped around the card later);
4. turn web links into smart-link cards;
5. save once, only if the body changed.

`--before N` is the page version just before the text update, so a successful update leaves the
page at N + 1. If the page is higher when it is first read, someone edited it in between: the work
still goes on top of their version and the output says `"editedDuringPublish": true`. If the page
is still at N, no text update landed (the publish was called off or failed): every leftover
placeholder of one of our attachments is embedded, even for a file the markdown dropped, and no
image is stripped, so the page shows what it showed before the publish.

Comments: a comment whose marker is already on the page is left alone. Otherwise its anchor is its
highlighted text, plus the words around its marker in version `before` when that version had one
(a comment with an empty highlight is anchored from that marker alone). With version `before`, a
comment stays inside the block that replaced its own, so deleting an item can't move its comment
onto a look-alike item. Open comments may move onto reworded text, but only with that old marker.
Without `--before` only exact matching runs, and an open comment that doesn't match is `stillDetached`.
When `--before` can't be read only exact matching runs too, but such a comment is `detached` with
reason `noBefore`, because it can't tell whether the comment was attached before. Resolved comments
are re-attached on an exact match only; that is allowed because probe P2 showed a re-inserted marker
keeps its comment resolved.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Set, Tuple

import cards
import images
import marker_wrap
import markers
import markdown_doc
from matcher import Anchor, align, find
from storage import apply_edits, element_ranges, tokenize
from textnorm import normalize
from visible_text import blocks

# Probe P2: a resolved comment's marker can be put back and the comment stays resolved.
REATTACH_RESOLVED = True


def _http(status: int) -> str:
    return "HTTP %d" % status if status else "network error"


def _plural(count: int, word: str) -> str:
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def _fail(page_id: str, message: str, up: Optional[Dict] = None) -> Tuple[Dict, int]:
    """An error output. When uploads already happened, they are still reported."""
    out: Dict = {"pageId": page_id, "error": message}
    if up is not None:
        for key in ("uploaded", "unchanged", "missingLocally", "failed"):
            out[key] = up[key]
    return out, 1


def _read_before(client, page_id: str, before: int) -> Optional[str]:
    status, old = client.read_version(page_id, before)
    if status != 200 or not isinstance(old, dict):
        return None
    try:
        return old["body"]["storage"]["value"]
    except (KeyError, TypeError):
        return None


def _anchor(before_body: Optional[str], ref: str, selection: str) -> Tuple[Anchor, bool]:
    """The comment's anchor, and whether its marker was found in the `before` body."""
    if before_body is not None:
        found = markers.anchor_for(before_body, ref, selection)
        if found is not None:
            return found, True
    return Anchor(normalize(selection)), False


def _usable(item: Dict) -> bool:
    """A comment can be re-attached only if it has a ref; its selection text may be empty."""
    return bool(item.get("ref"))


def _selection(item: Dict) -> str:
    selection = item.get("selection")
    return selection if isinstance(selection, str) else ""


def _reattach(body: str, comments: List[Dict], before_body: Optional[str],
              before_unreadable: bool = False) -> Tuple[str, Dict]:
    """Put back the markers of comments that aren't on the page. Return (body, counts).

    before_unreadable: `--before` was given but couldn't be read, so an open comment that
    doesn't match exactly is reported as detached (reason `noBefore`), not stillDetached.
    """
    counts: Dict = {"reattached": 0, "moved": [], "detached": [], "stillDetached": [],
                    "alreadyAttached": 0, "resolved": {"reattached": 0, "notFound": 0, "skipped": 0}}
    resolved_counts = counts["resolved"]
    on_page = markers.refs(body)
    doc = None  # the blocks of the current body; dropped whenever a wrap changes it
    old_texts = alignment = None
    if before_body is not None:
        # Wrapping a marker never changes the visible block texts, so this one alignment of
        # the old page's blocks onto the current ones holds for the whole run.
        old_texts = [block.text for block in blocks(before_body)]
        doc = blocks(body)
        alignment = align(old_texts, [block.text for block in doc])
    for item in comments:
        if not _usable(item):
            continue
        ref, selection = item["ref"], _selection(item)
        if ref in on_page:
            counts["alreadyAttached"] += 1
            continue
        resolved = item.get("status") == "resolved"
        if resolved and not REATTACH_RESOLVED:
            resolved_counts["skipped"] += 1
            continue

        anchor, had_marker = _anchor(before_body, ref, selection)
        if doc is None:
            doc = blocks(body)
        texts = [block.text for block in doc]
        result = find(anchor, texts, allow_move=had_marker and not resolved,
                      old_texts=old_texts, alignment=alignment)

        reason = result.reason or "textGone"
        if result.status in ("exact", "moved"):
            wrapped = marker_wrap.wrap(body, doc[result.block], result.start, result.end, ref)
            if wrapped != body:
                new_wording = texts[result.block][result.start:result.end]
                body, doc = wrapped, None
                on_page.add(ref)
                if resolved:
                    resolved_counts["reattached"] += 1
                elif result.status == "moved":
                    counts["moved"].append({"id": item.get("id"), "from": anchor.text, "to": new_wording})
                else:
                    counts["reattached"] += 1
                continue
            reason = "textGone"  # the words are there but there was no text to put a marker on

        if resolved:
            resolved_counts["notFound"] += 1
        elif had_marker:
            counts["detached"].append({"id": item.get("id"), "text": anchor.text, "reason": reason})
        elif before_unreadable:
            counts["detached"].append({"id": item.get("id"), "text": anchor.text, "reason": "noBefore"})
        else:
            counts["stillDetached"].append({"id": item.get("id"), "text": anchor.text})
    return body, counts


def _restore_leftovers(body: str, ours: Set[str]) -> Tuple[str, int]:
    """Embed every placeholder whose file name is one of our attachments; return (body, count).

    Each keeps its own alt text. The size isn't known here, so the embed has no width."""
    tokens = tokenize(body)
    inside = set()
    for first, last in element_ranges(tokens, "ac:image"):
        inside.update(range(first, last + 1))
    edits = []
    for i, token in enumerate(tokens):
        if (token.name == "img" and token.kind in ("empty", "start") and i not in inside
                and token.attrs.get("src") in ours):
            edits.append((token.start, token.end,
                          images.embed_markup(token.attrs.get("alt", ""), token.attrs["src"], None)))
    return apply_edits(body, edits), len(edits)


def _message(up: Dict, emb: Dict, comments: Dict, made: int) -> str:
    parts = []
    if up["uploaded"]:
        parts.append("uploaded %s" % _plural(len(up["uploaded"]), "image"))
    if emb["embedded"]:
        parts.append("embedded %s" % _plural(emb["embedded"], "image"))
    if emb["stripped"]:
        parts.append("removed %s that couldn't upload" % _plural(len(emb["stripped"]), "image"))
    back = comments["reattached"] + len(comments["moved"]) + comments["resolved"]["reattached"]
    if back:
        parts.append("re-attached %s" % _plural(back, "comment"))
    if made:
        parts.append("turned %s into cards" % _plural(made, "link"))
    return "Finished the update: " + (", ".join(parts) if parts else "tidied the page")


def run(page_id: str, md_path: str, before: Optional[int], client) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints."""
    try:
        with open(md_path, "r", encoding="utf-8") as handle:
            md = handle.read()
    except (OSError, UnicodeDecodeError) as err:
        return _fail(page_id, "couldn't read %s: %s" % (md_path, getattr(err, "strerror", None) or err))
    pictures = markdown_doc.local_images(md, os.path.dirname(os.path.abspath(md_path)))
    links = markdown_doc.web_links(md)

    existing = images.notes(client, page_id)
    up = images.upload_changed(client, page_id, pictures, existing)

    status, page = client.read_page(page_id)
    try:
        if status != 200:
            raise KeyError(status)
        original = page["body"]["storage"]["value"]
        version = page["version"]["number"]
    except (KeyError, TypeError):
        return _fail(page_id, "couldn't read the page (%s)" % _http(status), up)

    edited = before is not None and version > before + 1
    called_off = before is not None and version == before
    if called_off:
        # No text update landed: strip nothing (an image that couldn't upload keeps the
        # attachment it had), and put back every image `prepare` took off, below.
        pictures = [image for image in pictures if image.src in up["ready"]]
    body, emb = images.embed(original, pictures, up["ready"])
    if called_off:
        ours = {name for name, note in existing.items() if note.startswith(images.OUR_MARK)}
        body, restored = _restore_leftovers(body, ours)
        emb["embedded"] += restored

    status, listed = client.inline_comments(page_id)
    if status != 200 or not isinstance(listed, list):
        return _fail(page_id, "couldn't read the page's comments (%s); nothing was saved"
                     % _http(status), up)
    warning = None
    before_body = None
    if before is not None:
        on_page = markers.refs(body)
        if any(_usable(item) and item["ref"] not in on_page for item in listed):
            before_body = _read_before(client, page_id, before)
            if before_body is None:
                warning = ("couldn't read version %d, so only exact matching ran; open comments that "
                           "didn't match are listed as detached (reason noBefore) because it can't "
                           "tell whether they were attached before" % before)
    body, comment_counts = _reattach(body, listed, before_body, before_unreadable=warning is not None)

    body, card_counts = cards.make_cards(body, links)

    if body != original:
        message = _message(up, emb, comment_counts, card_counts["made"])
        status, saved = client.save_body(page, body, message)
        if status != 200:
            hint = ("; the page changed during the publish, so publishing again will show what changed"
                    if status == 409 else "")
            return _fail(page_id, "couldn't save the page (%s)%s" % (_http(status), hint), up)
        try:
            version = saved["version"]["number"]
        except (KeyError, TypeError):
            version += 1

    out: Dict = {key: up[key] for key in ("uploaded", "unchanged", "missingLocally", "failed")}
    for key in ("embedded", "alreadyEmbedded", "stripped", "notOnPage"):
        out[key] = emb[key]
    out["cards"] = card_counts
    out["comments"] = comment_counts
    out["version"] = version
    out["pageId"] = page_id
    if warning:
        out["warning"] = warning
    if edited:
        out["editedDuringPublish"] = True
    failed = any(out[key] for key in ("failed", "missingLocally", "notOnPage"))
    return out, 1 if failed else 0
