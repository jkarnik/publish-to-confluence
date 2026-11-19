"""Merge a proposed markdown file into the local file: preview, then apply with a backup."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, Optional, Tuple

BACKUP_DIR = os.path.expanduser("~/.claude/publish-to-confluence/backups")
SNIPPET = 100


def preview(file_text: str, proposed_text: str) -> Dict:
    """Describe what applying the proposed text would change, without writing."""
    raise NotImplementedError


def apply(file_path: str, proposed_path: str, backup_dir: str = BACKUP_DIR, now: Optional[datetime] = None) -> Dict:
    """Back up the file, then write the merged result."""
    raise NotImplementedError


def run_preview(file_path: str, proposed_path: str) -> Tuple[Dict, int]:
    """Return (output dict, exit code) for the preview mode."""
    raise NotImplementedError


def run_apply(file_path: str, proposed_path: str) -> Tuple[Dict, int]:
    """Return (output dict, exit code) for the apply mode."""
    raise NotImplementedError
