"""Entry point: python3 -I scripts/confluence_rest.py <mode> [arguments].

Parses the mode and its arguments, builds the REST client for the modes that
talk to Confluence, calls the mode module's run(), prints its result as JSON and
returns the exit code (0 OK, 1 partly failed or bad usage, 2 setup or token
missing). The token is never printed.
"""
import json
import os
import re
import sys

# "python3 -I" leaves this folder off sys.path, so put it first.
_HERE = os.path.dirname(os.path.realpath(__file__))
if sys.path[:1] != [_HERE]:
    sys.path.insert(0, _HERE)

import local_config  # noqa: E402
import merge_files  # noqa: E402
import mode_check  # noqa: E402
import mode_comments  # noqa: E402
import mode_download  # noqa: E402
import mode_finish  # noqa: E402
import mode_prepare  # noqa: E402
import rest_client  # noqa: E402

# mode -> (usage text, number of positional arguments)
USAGE = {
    "check": ("check", 0),
    "comments": ("comments <pageId> <file>", 2),
    "prepare": ("prepare <pageId> <file> [--overwrite]", 2),
    "finish": ("finish <pageId> <file> [--before <version>]", 2),
    "preview-merge": ("preview-merge <file> <proposed>", 2),
    "apply-merge": ("apply-merge <file> <proposed>", 2),
    "download": ("download <pageId> <filename> <dest>", 3),
}
CLIENT_MODES = ("comments", "prepare", "finish", "download")


class UsageError(Exception):
    pass


def _usage_text(mode=None):
    if mode in USAGE:
        return "usage: confluence_rest.py " + USAGE[mode][0]
    return "usage: confluence_rest.py <mode> [arguments]; modes: " + ", ".join(USAGE)


def _parse(mode, args):
    """Return (positionals, options) for the mode, or raise UsageError."""
    positionals = []
    options = {"overwrite": False, "before": None}
    i = 0
    while i < len(args):
        arg = args[i]
        if mode == "prepare" and arg == "--overwrite":
            options["overwrite"] = True
        elif mode == "finish" and (arg == "--before" or arg.startswith("--before=")):
            if arg == "--before":
                i += 1
                value = args[i] if i < len(args) else ""
            else:
                value = arg[len("--before="):]
            if not re.fullmatch(r"[0-9]+", value):
                raise UsageError(_usage_text(mode))
            options["before"] = int(value)
        elif arg.startswith("--"):
            raise UsageError(_usage_text(mode))
        else:
            positionals.append(arg)
        i += 1
    if len(positionals) != USAGE[mode][1]:
        raise UsageError(_usage_text(mode))
    return positionals, options


def _print(out):
    print(json.dumps(out, indent=2, ensure_ascii=False))


def _build_client():
    """Return (client, token, None) or (None, None, (error output, exit code))."""
    setup = local_config.read_setup()
    state = setup.get("setup")
    if state != "ok":
        return None, None, ({"error": "setup", "setup": state}, 2)
    credentials = local_config.read_credentials()
    if not credentials:
        return None, None, ({"error": "token", "token": "missing"}, 2)
    email, token = credentials
    return rest_client.RestClient(setup.get("site"), email, token), token, None


def _dispatch(mode, positionals, options, client):
    if mode == "check":
        return mode_check.run(local_config.SETUP_PATH, local_config.ENV_PATH)
    if mode == "comments":
        return mode_comments.run(positionals[0], os.path.abspath(positionals[1]), client)
    if mode == "prepare":
        return mode_prepare.run(positionals[0], os.path.abspath(positionals[1]),
                                options["overwrite"], client)
    if mode == "finish":
        return mode_finish.run(positionals[0], os.path.abspath(positionals[1]),
                               options["before"], client)
    if mode == "preview-merge":
        return merge_files.run_preview(os.path.abspath(positionals[0]),
                                       os.path.abspath(positionals[1]))
    if mode == "apply-merge":
        return merge_files.run_apply(os.path.abspath(positionals[0]),
                                     os.path.abspath(positionals[1]))
    return mode_download.run(positionals[0], positionals[1],
                             os.path.abspath(positionals[2]), client)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in USAGE:
        _print({"error": _usage_text()})
        return 1
    mode = args[0]
    try:
        positionals, options = _parse(mode, args[1:])
        if mode in CLIENT_MODES and not re.fullmatch(r"[0-9]+", positionals[0]):
            raise UsageError(_usage_text(mode))
    except UsageError as error:
        _print({"error": str(error)})
        return 1

    client = token = None
    try:
        if mode in CLIENT_MODES:
            client, token, failure = _build_client()
            if failure:
                _print(failure[0])
                return failure[1]
        out, code = _dispatch(mode, positionals, options, client)
    except Exception as error:  # noqa: BLE001 - report anything else as JSON
        message = "%s: %s" % (type(error).__name__, error)
        if token:
            message = message.replace(token, "***")  # never print the token
        _print({"error": message})
        return 1
    _print(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
