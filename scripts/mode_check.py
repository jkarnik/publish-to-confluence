"""Mode `check`: report whether setup and credentials are in place."""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple


def run(setup_path: str, env_path: str, client_factory: Optional[Callable] = None) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints.

    client_factory builds the REST client; None means rest_client.RestClient.
    """
    raise NotImplementedError
