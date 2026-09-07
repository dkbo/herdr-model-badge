"""Turning one herdr AgentInfo into the token set we report back to herdr."""

import unittest

from herdr_model_badge import badge

TOKEN_NAMES = ("badge", "model", "effort", "perm", "ctx")


def fake_reader(values):
    def read(session, home=None):
        return dict(values)

    return read


class TokensForTests(unittest.TestCase):
    def test_readable_agent_gets_a_composed_badge_plus_the_parts(self):
        agent = {"pane_id": "w1:p1", "agent": "claude"}
        got = badge.tokens_for(agent, resolve=lambda kind: fake_reader(
            {"model": "opus 5", "effort": "high", "perm": "auto", "ctx": "104k"}
        ))
        self.assertEqual(got["badge"], "opus 5 · high")
        self.assertEqual(got["model"], "opus 5")
        self.assertEqual(got["effort"], "high")
        self.assertEqual(got["perm"], "auto")
        self.assertEqual(got["ctx"], "104k")

    def test_every_token_is_always_present_so_stale_values_get_cleared(self):
        agent = {"pane_id": "w1:p1", "agent": "claude"}
        got = badge.tokens_for(agent, resolve=lambda kind: fake_reader({"model": "opus 5"}))
        self.assertEqual(sorted(got), sorted(TOKEN_NAMES))
        self.assertEqual(got["badge"], "opus 5")
        self.assertIsNone(got["effort"])
        self.assertIsNone(got["perm"])
        self.assertIsNone(got["ctx"])

    def test_an_agent_with_no_provider_clears_every_token(self):
        agent = {"pane_id": "w1:p1", "agent": "cursor"}
        got = badge.tokens_for(agent, resolve=lambda kind: None)
        self.assertEqual(sorted(got), sorted(TOKEN_NAMES))
        self.assertTrue(all(value is None for value in got.values()))

    def test_a_pane_with_no_agent_clears_every_token(self):
        got = badge.tokens_for({"pane_id": "w1:p1"}, resolve=lambda kind: None)
        self.assertTrue(all(value is None for value in got.values()))

    def test_a_failing_provider_clears_every_token_instead_of_raising(self):
        def explode(session, home=None):
            raise OSError("session file vanished mid-read")

        got = badge.tokens_for(
            {"pane_id": "w1:p1", "agent": "claude"}, resolve=lambda kind: explode
        )
        self.assertTrue(all(value is None for value in got.values()))


class SessionOfTests(unittest.TestCase):
    def test_session_id_and_path_are_lifted_out_of_agent_info(self):
        agent = {
            "pane_id": "w1:p1",
            "agent": "claude",
            "cwd": "/home/x/project",
            "agent_session": {"kind": "id", "value": "sess-1"},
        }
        self.assertEqual(
            badge.session_of(agent),
            {"session_id": "sess-1", "session_path": None, "cwd": "/home/x/project"},
        )

    def test_a_path_kind_session_reference_becomes_the_session_path(self):
        agent = {
            "pane_id": "w1:p1",
            "agent": "agy",
            "agent_session": {"kind": "path", "value": "/tmp/transcript.jsonl"},
        }
        session = badge.session_of(agent)
        self.assertEqual(session["session_path"], "/tmp/transcript.jsonl")
        self.assertIsNone(session["session_id"])

    def test_an_agent_without_a_reported_session_still_yields_a_session_shape(self):
        session = badge.session_of({"pane_id": "w1:p1", "agent": "claude"})
        self.assertIsNone(session["session_id"])
        self.assertIsNone(session["session_path"])


if __name__ == "__main__":
    unittest.main()


class NeedsReportTests(unittest.TestCase):
    TOKENS = {"badge": "opus 5 · high", "model": "opus 5", "effort": "high",
              "perm": None, "ctx": None}

    def test_a_pane_that_already_matches_needs_no_report(self):
        agent = {"tokens": {"badge": "opus 5 · high", "model": "opus 5", "effort": "high"}}
        self.assertFalse(badge.needs_report(agent, self.TOKENS))

    def test_a_pane_with_no_tokens_yet_needs_a_report(self):
        self.assertTrue(badge.needs_report({}, self.TOKENS))

    def test_a_changed_value_needs_a_report(self):
        agent = {"tokens": {"badge": "opus 5 · low", "model": "opus 5", "effort": "low"}}
        self.assertTrue(badge.needs_report(agent, self.TOKENS))

    def test_a_leftover_value_needs_clearing(self):
        agent = {"tokens": {"ctx": "104k"}}
        self.assertTrue(badge.needs_report({"tokens": {}}, {"ctx": None}) is False)
        self.assertTrue(badge.needs_report(agent, {"ctx": None}))

    def test_tokens_owned_by_other_sources_are_ignored(self):
        agent = {"tokens": {"badge": "opus 5 · high", "model": "opus 5", "effort": "high",
                            "jj_status": "dirty"}}
        self.assertFalse(badge.needs_report(agent, self.TOKENS))
