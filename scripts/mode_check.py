"""Mode `check`: report whether setup and credentials are in place."""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

import local_config


def _token_state(client) -> Tuple[str, str]:
    """Test the token with one read. Return (state, plain-English detail).

    The detail never repeats the server's own message: it could echo input.
    """
    status, payload = client.current_user()
    if status == 200:
        if isinstance(payload, dict) and payload.get("accountId"):
            return "ok", "the token works"
        return "invalid", "the token didn't identify a user"
    if status == 401:
        return "invalid", "the token was rejected (401)"
    if status == 403:
        return "blocked", "your organization blocks API tokens (403)"
    if status == 0:
        return "invalid", "couldn't reach the site"
    return "invalid", "the site answered with an error (HTTP %s)" % status


def run(setup_path: str, env_path: str, client_factory: Optional[Callable] = None) -> Tuple[Dict, int]:
    """Return (output dict, exit code); never prints.

    client_factory builds the REST client; None means rest_client.RestClient.
    """
    setup = local_config.read_setup(setup_path)
    credentials = local_config.read_credentials(env_path)

    if credentials is None:
        token, detail = "missing", "the token file is missing or not filled in"
    elif setup["setup"] != "ok":
        token, detail = "unchecked", "fix SETUP.md first, so there is a site to test the token against"
    else:
        if client_factory is None:
            import rest_client
            client_factory = rest_client.RestClient
        email, secret = credentials
        token, detail = _token_state(client_factory(setup["site"], email, secret))

    output = {
        "setup": setup["setup"],
        "parent": setup["parent"],
        "site": setup["site"],
        "token": token,
        "tokenDetail": detail,
    }
    code = 0 if setup["setup"] == "ok" and token == "ok" else 2
    return output, code
