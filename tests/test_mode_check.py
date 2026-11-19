"""Tests for scripts/mode_check.py: the `check` mode."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import unittest

import helpers
import mode_check

SITE = "https://example.atlassian.net"
PAGE = SITE + "/wiki/spaces/ABC/pages/123/Some+Title"
EMAIL = "someone@example.com"
TOKEN = "tok-secret-12345"
KEYS = {"setup", "parent", "site", "token", "tokenDetail"}


def write(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


class Factory:
    """Records its calls and hands back one FakeClient."""

    def __init__(self, **client_args):
        self.client = helpers.FakeClient(**client_args)
        self.calls = []

    def __call__(self, site, email, token):
        self.calls.append((site, email, token))
        return self.client


def files(folder, parent=PAGE, credentials=True):
    """Write SETUP.md and the token file; None leaves a file out."""
    setup = os.path.join(folder, "SETUP.md")
    env = os.path.join(folder, "atlassian-api.env")
    if parent is not None:
        write(folder, "SETUP.md", "Parent: %s\n" % parent)
    if credentials:
        write(folder, "atlassian-api.env",
              "ATLASSIAN_EMAIL=%s\nATLASSIAN_API_TOKEN=%s\n" % (EMAIL, TOKEN))
    return setup, env


class CheckTests(unittest.TestCase):
    def test_all_ok(self):
        with helpers.TempDir() as folder:
            setup, env = files(folder)
            factory = Factory()
            out, code = mode_check.run(setup, env, factory)
        self.assertEqual(code, 0)
        self.assertEqual(set(out), KEYS)
        self.assertEqual(out["setup"], "ok")
        self.assertEqual(out["parent"], PAGE)
        self.assertEqual(out["site"], SITE + "/wiki")
        self.assertEqual(out["token"], "ok")
        self.assertIsInstance(out["tokenDetail"], str)
        self.assertEqual(factory.calls, [(SITE + "/wiki", EMAIL, TOKEN)])

    def test_no_credentials(self):
        with helpers.TempDir() as folder:
            setup, env = files(folder, credentials=False)
            factory = Factory()
            out, code = mode_check.run(setup, env, factory)
        self.assertEqual(code, 2)
        self.assertEqual(set(out), KEYS)
        self.assertEqual(out["setup"], "ok")
        self.assertEqual(out["token"], "missing")
        self.assertTrue(out["tokenDetail"])
        self.assertEqual(factory.calls, [])

    def test_401_invalid(self):
        with helpers.TempDir() as folder:
            setup, env = files(folder)
            factory = Factory(fail={"current_user": (401, "Unauthorized")})
            out, code = mode_check.run(setup, env, factory)
        self.assertEqual(code, 2)
        self.assertEqual(out["setup"], "ok")
        self.assertEqual(out["token"], "invalid")
        self.assertIn("401", out["tokenDetail"])

    def test_403_blocked(self):
        with helpers.TempDir() as folder:
            setup, env = files(folder)
            factory = Factory(fail={"current_user": (403, "Forbidden")})
            out, code = mode_check.run(setup, env, factory)
        self.assertEqual(code, 2)
        self.assertEqual(out["token"], "blocked")
        self.assertIn("403", out["tokenDetail"])

    def test_network_invalid_with_detail(self):
        with helpers.TempDir() as folder:
            setup, env = files(folder)
            factory = Factory(fail={"current_user": (0, "getaddrinfo failed")})
            out, code = mode_check.run(setup, env, factory)
        self.assertEqual(code, 2)
        self.assertEqual(out["token"], "invalid")
        self.assertIn("reach", out["tokenDetail"])
        self.assertNotIn("getaddrinfo", out["tokenDetail"])

    def test_other_status_invalid(self):
        with helpers.TempDir() as folder:
            setup, env = files(folder)
            factory = Factory(fail={"current_user": (500, "boom " + TOKEN)})
            out, code = mode_check.run(setup, env, factory)
        self.assertEqual(code, 2)
        self.assertEqual(out["token"], "invalid")
        self.assertIn("HTTP 500", out["tokenDetail"])
        self.assertNotIn("boom", out["tokenDetail"])

    def test_200_without_account_id_invalid(self):
        for user in ({}, {"accountId": ""}, {"displayName": "Test User"}):
            with helpers.TempDir() as folder:
                setup, env = files(folder)
                factory = Factory(user=user)
                out, code = mode_check.run(setup, env, factory)
            self.assertEqual(code, 2)
            self.assertEqual(out["token"], "invalid")
            self.assertIn("didn't identify a user", out["tokenDetail"])

    def test_setup_missing_token_unchecked(self):
        with helpers.TempDir() as folder:
            setup, env = files(folder, parent=None)
            factory = Factory()
            out, code = mode_check.run(setup, env, factory)
        self.assertEqual(code, 2)
        self.assertEqual(set(out), KEYS)
        self.assertEqual(out["setup"], "missing")
        self.assertIsNone(out["parent"])
        self.assertIsNone(out["site"])
        self.assertEqual(out["token"], "unchecked")
        self.assertTrue(out["tokenDetail"])
        self.assertEqual(factory.calls, [])

    def test_placeholder_and_invalid_setup_token_unchecked(self):
        for parent, state in (("(paste the address of a Confluence page or folder)", "placeholder"),
                              ("not an address", "invalid")):
            with helpers.TempDir() as folder:
                setup, env = files(folder, parent=parent)
                factory = Factory()
                out, code = mode_check.run(setup, env, factory)
            self.assertEqual(code, 2)
            self.assertEqual(out["setup"], state)
            self.assertEqual(out["token"], "unchecked")
            self.assertEqual(factory.calls, [])

    def test_short_link(self):
        short = SITE + "/wiki/x/AbCdEf"
        with helpers.TempDir() as folder:
            setup, env = files(folder, parent=short)
            factory = Factory()
            out, code = mode_check.run(setup, env, factory)
        self.assertEqual(code, 2)
        self.assertEqual(out["setup"], "short-link")
        self.assertEqual(out["parent"], short)
        self.assertIsNone(out["site"])
        self.assertEqual(out["token"], "unchecked")
        self.assertEqual(factory.calls, [])

    def test_no_credentials_and_no_setup(self):
        with helpers.TempDir() as folder:
            setup, env = files(folder, parent=None, credentials=False)
            factory = Factory()
            out, code = mode_check.run(setup, env, factory)
        self.assertEqual(code, 2)
        self.assertEqual(out["setup"], "missing")
        self.assertEqual(out["token"], "missing")
        self.assertEqual(factory.calls, [])

    def test_never_prints_secrets(self):
        cases = [
            {},
            {"fail": {"current_user": (401, "bad " + TOKEN + " " + EMAIL)}},
            {"fail": {"current_user": (403, EMAIL + TOKEN)}},
            {"fail": {"current_user": (0, EMAIL + TOKEN)}},
            {"fail": {"current_user": (500, EMAIL + TOKEN)}},
            {"user": {"displayName": EMAIL + TOKEN}},
        ]
        for client_args in cases:
            with helpers.TempDir() as folder:
                setup, env = files(folder)
                out, code = mode_check.run(setup, env, Factory(**client_args))
            text = json.dumps(out)
            self.assertNotIn(TOKEN, text)
            self.assertNotIn(EMAIL, text)

    def test_default_factory_is_the_rest_client(self):
        # rest_client.RestClient is still unimplemented in this worktree, so only
        # check that the default factory is looked up (and raises its own error)
        # rather than silently doing nothing.
        import rest_client
        seen = []
        original = rest_client.RestClient
        rest_client.RestClient = lambda site, email, token: (
            seen.append((site, email, token)) or helpers.FakeClient())
        try:
            with helpers.TempDir() as folder:
                setup, env = files(folder)
                out, code = mode_check.run(setup, env)
        finally:
            rest_client.RestClient = original
        self.assertEqual((out["token"], code), ("ok", 0))
        self.assertEqual(seen, [(SITE + "/wiki", EMAIL, TOKEN)])


if __name__ == "__main__":
    unittest.main()
