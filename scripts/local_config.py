"""Reads SETUP.md and atlassian-api.env from the repo root."""
from __future__ import annotations

import os
import re
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SETUP_PATH: str = os.path.join(REPO_ROOT, "SETUP.md")
ENV_PATH: str = os.path.join(REPO_ROOT, "atlassian-api.env")
PLACEHOLDER = "(paste the address of a Confluence page or folder)"

_ID = re.compile(r"[0-9]+\Z")


def _result(setup: str, parent: Optional[str] = None,
            site: Optional[str] = None) -> Dict[str, Optional[str]]:
    return {"setup": setup, "parent": parent, "site": site}


def _has_page_or_folder(segments) -> bool:
    for kind, number in zip(segments, segments[1:]):
        if kind in ("pages", "folder") and _ID.match(number):
            return True
    return False


def parse_parent(address: str) -> Dict[str, Optional[str]]:
    """Return {"setup", "parent", "site"}."""
    text = (address or "").strip()
    if not text or text == PLACEHOLDER:
        return _result("placeholder")

    try:
        parts = urlsplit(text)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return _result("invalid", text)
    if (parts.scheme != "https" or not host or parts.username is not None
            or re.search(r"\s", text) or not parts.path.startswith("/wiki/")):
        return _result("invalid", text)

    segments = parts.path[len("/wiki/"):].split("/")
    if segments[0] == "x" and len(segments) > 1 and segments[1]:
        return _result("short-link", text)
    if not _has_page_or_folder(segments):
        return _result("invalid", text)

    site = "https://" + host + (":%d" % port if port else "") + "/wiki"
    return _result("ok", text, site)


def read_setup(path: str = SETUP_PATH) -> Dict[str, Optional[str]]:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return _result("missing")
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("parent:"):
            return parse_parent(stripped.split(":", 1)[1])
    return _result("placeholder")


def read_credentials(path: str = ENV_PATH) -> Optional[Tuple[str, str]]:
    """Return (email, token) or None."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    values: Dict[str, str] = {}
    for line in lines:
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    email = values.get("ATLASSIAN_EMAIL", "")
    token = values.get("ATLASSIAN_API_TOKEN", "")
    if not email or not token:
        return None
    return email, token
