"""Reads SETUP.md and atlassian-api.env from the repo root."""
from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SETUP_PATH: str = os.path.join(REPO_ROOT, "SETUP.md")
ENV_PATH: str = os.path.join(REPO_ROOT, "atlassian-api.env")
PLACEHOLDER = "(paste the address of a Confluence page or folder)"


def parse_parent(address: str) -> Dict[str, Optional[str]]:
    """Return {"setup", "parent", "site"}."""
    raise NotImplementedError


def read_setup(path: str = SETUP_PATH) -> Dict[str, Optional[str]]:
    raise NotImplementedError


def read_credentials(path: str = ENV_PATH) -> Optional[Tuple[str, str]]:
    """Return (email, token) or None."""
    raise NotImplementedError
