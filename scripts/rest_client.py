"""Confluence REST client. Every call returns (status, payload); status 0 = network error,
payload {"message": ...}."""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple


class RestClient:
    def __init__(self, site: str, email: str, token: str, opener: Optional[Callable] = None):
        raise NotImplementedError

    def current_user(self) -> Tuple[int, dict]:
        raise NotImplementedError

    def read_page(self, page_id: str, expand: str = "body.storage,version") -> Tuple[int, dict]:
        raise NotImplementedError

    def read_version(self, page_id: str, number: int) -> Tuple[int, dict]:
        """Historical body.storage."""
        raise NotImplementedError

    def save_body(self, page: dict, body: str, message: str) -> Tuple[int, dict]:
        """Minor edit, version + 1."""
        raise NotImplementedError

    def attachments(self, page_id: str) -> Tuple[int, List[dict]]:
        """All pages of results."""
        raise NotImplementedError

    def upload(self, page_id: str, path: str, name: str, comment: str) -> Tuple[int, dict]:
        raise NotImplementedError

    def inline_comments(self, page_id: str) -> Tuple[int, List[dict]]:
        """[{"id", "status", "ref", "selection"}]."""
        raise NotImplementedError

    def download(self, page_id: str, filename: str) -> Tuple[int, bytes]:
        raise NotImplementedError
