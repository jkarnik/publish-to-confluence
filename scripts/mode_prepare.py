"""Mode `prepare`: get a page ready to receive the markdown file.

Run just before a republish's markdown text update. In one minor edit it makes plain what would
make Confluence refuse that update (probe P3): embedded attachment images go back to placeholders
and every macro that blocks it becomes plain content (flatten.make_plain: Jira issues become links,
panels keep their text, a table of contents goes). Cards, `code` and `status` macros and mentions
are accepted as they are, and comment markers are never touched. If a Jira issue can't become a
link, the publish is called off, so nothing at all is saved and the exit code is 1.
"""
from __future__ import annotations

import os
from typing import Dict, List, Tuple

import flatten
import images
import markdown_doc


class _Listing:
    """A client that hands back one attachment listing already read, for images.notes."""

    def __init__(self, listing):
        self._listing = listing

    def attachments(self, _page_id):
        return self._listing


def _fail(page_id: str, reason: str) -> Tuple[Dict, int]:
    return {"pageId": page_id, "error": reason}, 1


def _why(status: int, payload) -> str:
    message = payload.get("message") if isinstance(payload, dict) else None
    if status == 0:
        return message or "network error"
    return "HTTP %d: %s" % (status, message) if message else "HTTP %d" % status


def _count(n: int, one: str, many: str) -> str:
    return "%d %s" % (n, one if n == 1 else many)


# How each macro kind reads in the save message: (one, many). Others read "<name> macro(s)".
_KINDS = {
    "jiraList": ("Jira list", "Jira lists"),
    "info": ("info panel", "info panels"),
    "note": ("note panel", "note panels"),
    "tip": ("tip panel", "tip panels"),
    "warning": ("warning panel", "warning panels"),
    "panel": ("panel", "panels"),
    "expand": ("expand section", "expand sections"),
    "toc": ("table of contents", "tables of contents"),
    "children": ("child page list", "child page lists"),
    "excerpt": ("excerpt", "excerpts"),
}


def _kind(name: str, n: int) -> str:
    one, many = _KINDS.get(name, (name + " macro", name + " macros"))
    return _count(n, one, many)


def _join(parts: List[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _message(swapped: int, removed: int, counts: Dict[str, int]) -> str:
    parts: List[str] = []
    if swapped:
        parts.append("swap %s for %s" % (_count(swapped, "image", "images"),
                                         "a placeholder" if swapped == 1 else "placeholders"))
    if removed:
        parts.append("remove %s" % _count(removed, "unreferenced image", "unreferenced images"))
    jira = counts.get("jira", 0)
    if jira:
        parts.append("turn %s into %s" % (_count(jira, "Jira issue", "Jira issues"),
                                          "a link" if jira == 1 else "links"))
    others = [_kind(name, n) for name, n in sorted(counts.items()) if name != "jira" and n]
    if others:
        parts.append("make %s plain" % _join(others))
    text = _join(parts)
    return text[:1].upper() + text[1:] + " before republishing"


def run(page_id: str, md_path: str, overwrite: bool, client) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints."""
    try:
        with open(md_path, encoding="utf-8", errors="replace") as handle:
            markdown = handle.read()
    except OSError as error:
        return _fail(page_id, "could not read %s: %s" % (md_path, error.strerror or error))
    referenced = {image.name for image in
                  markdown_doc.local_images(markdown, os.path.dirname(os.path.abspath(md_path)))}

    status, page = client.read_page(page_id, "body.storage,version,body.view")
    if status != 200:
        return _fail(page_id, "could not read the page (%s)" % _why(status, page))
    try:
        body = page["body"]["storage"]["value"]
        version = int(page["version"]["number"])
    except (KeyError, TypeError, ValueError):
        return _fail(page_id, "could not read the page (the reply has no body or version)")
    view = ((page.get("body") or {}).get("view") or {}).get("value") or ""

    status, listing = client.attachments(page_id)
    if status != 200:
        return _fail(page_id, "could not list the page's attachments (%s)" % _why(status, listing))
    ours = {name for name, note in images.notes(_Listing((status, listing)), page_id).items()
            if note.startswith(images.OUR_MARK)}

    removed = 0
    if overwrite:
        body, removed = images.remove_embeds(body, referenced)
    body, swapped = images.to_placeholders(body, ours | referenced)
    body, counts, unresolved = flatten.make_plain(body, view)

    if unresolved:
        # Confluence would refuse the text update while a Jira issue macro stays, so the publish
        # is called off: change nothing on the page, and report no work done.
        return {"pageId": page_id, "version": version, "unembedded": 0,
                "madePlain": {"jira": 0, "unresolved": unresolved},
                "removedUnreferenced": 0}, 1

    out: Dict = {"pageId": page_id, "version": version, "unembedded": swapped,
                 "madePlain": dict(counts, unresolved=unresolved),
                 "removedUnreferenced": removed}
    if not (swapped or removed or any(counts.values())):
        return out, 0

    status, saved = client.save_body(page, body, _message(swapped, removed, counts))
    if status != 200:
        # Nothing was changed on the page, so no counts of work done.
        out.update({"unembedded": 0, "madePlain": {"jira": 0, "unresolved": unresolved},
                    "removedUnreferenced": 0,
                    "error": "could not save the page (%s); it was not changed"
                             % _why(status, saved)})
        return out, 1
    try:
        out["version"] = int(saved["version"]["number"])
    except (KeyError, TypeError, ValueError):
        out["version"] = version + 1
    return out, 0
