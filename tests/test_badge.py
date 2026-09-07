"""Turning one herdr AgentInfo into the token set we report back to herdr."""

import unittest

from herdr_model_badge import badge

TOKEN_NAMES = ("badge", "model", "effort", "perm", "ctx",
               "usage", "usage_session", "usage_period")


class NoCache:
    """Stands in for the statusline cache in tests that are not about it."""

    @staticmethod
    def read(pane_id, session_id):
        return {}


NO_CACHE = NoCache()


def fake_reader(values):
    def read(session, home=None):
        return dict(values)

    return read


class TokensForTests(unittest.TestCase):
    def test_readable_agent_gets_a_composed_badge_plus_the_parts(self):
        agent = {"pane_id": "w1:p1", "agent": "claude"}
        got = badge.tokens_for(agent, resolve=lambda kind: fake_reader(
            {"model": "opus 5", "effort": "high", "perm": "auto", "ctx": "104k"}
        ), cache=NO_CACHE)
        self.assertEqual(got["badge"], "opus 5 · high")
        self.assertEqual(got["model"], "opus 5")
        self.assertEqual(got["effort"], "high")
        self.assertEqual(got["perm"], "auto")
        self.assertEqual(got["ctx"], "104k")

    def test_every_token_is_always_present_so_stale_values_get_cleared(self):
        agent = {"pane_id": "w1:p1", "agent": "claude"}
        got = badge.tokens_for(agent, resolve=lambda kind: fake_reader({"model": "opus 5"}),
                               cache=NO_CACHE)
        self.assertEqual(sorted(got), sorted(TOKEN_NAMES))
        self.assertEqual(got["badge"], "opus 5")
        self.assertIsNone(got["effort"])
        self.assertIsNone(got["perm"])
        self.assertIsNone(got["ctx"])

    def test_an_agent_with_no_provider_clears_every_token(self):
        agent = {"pane_id": "w1:p1", "agent": "cursor"}
        got = badge.tokens_for(agent, resolve=lambda kind: None, cache=NO_CACHE)
        self.assertEqual(sorted(got), sorted(TOKEN_NAMES))
        self.assertTrue(all(value is None for value in got.values()))

    def test_a_pane_with_no_agent_clears_every_token(self):
        got = badge.tokens_for({"pane_id": "w1:p1"}, resolve=lambda kind: None,
                               cache=NO_CACHE)
        self.assertTrue(all(value is None for value in got.values()))

    def test_a_failing_provider_clears_every_token_instead_of_raising(self):
        def explode(session, home=None):
            raise OSError("session file vanished mid-read")

        got = badge.tokens_for(
            {"pane_id": "w1:p1", "agent": "claude"}, resolve=lambda kind: explode,
            cache=NO_CACHE
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
            {
                "pane_id": "w1:p1",
                "session_id": "sess-1",
                "session_path": None,
                "cwd": "/home/x/project",
            },
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


class MergeTests(unittest.TestCase):
    def test_the_statusline_wins_for_the_values_only_it_can_see(self):
        merged = badge.merge({"ctx": "191k"}, {"ctx": "6%", "usage": "5h:6%"})
        self.assertEqual(merged["ctx"], "6%")
        self.assertEqual(merged["usage"], "5h:6%")

    def test_the_transcript_wins_for_the_model_it_names_precisely(self):
        merged = badge.merge({"model": "opus 5", "effort": "high"},
                             {"model": "claude opus 5", "effort": "medium"})
        self.assertEqual(merged["model"], "opus 5")
        self.assertEqual(merged["effort"], "high")

    def test_the_statusline_fills_a_gap_the_transcript_left(self):
        merged = badge.merge({}, {"model": "opus 5"})
        self.assertEqual(merged["model"], "opus 5")

    def test_empty_overlay_values_never_overwrite(self):
        merged = badge.merge({"ctx": "191k"}, {"ctx": None})
        self.assertEqual(merged["ctx"], "191k")


class StatuslineOverlayTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        from herdr_model_badge import statusline

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = statusline.Cache(self.tmp.name)

    def test_usage_seen_by_the_statusline_survives_into_a_later_event(self):
        self.cache.write("w1:p1", "sess-1", {"ctx": "6%", "usage": "5h:6%  wk:4%"})
        agent = {
            "pane_id": "w1:p1",
            "agent": "claude",
            "agent_session": {"kind": "id", "value": "sess-1"},
        }
        got = badge.tokens_for(
            agent,
            resolve=lambda kind: fake_reader({"model": "opus 5", "effort": "high",
                                             "ctx": "191k"}),
            cache=self.cache,
        )
        self.assertEqual(got["ctx"], "6%")
        self.assertEqual(got["usage"], "5h:6%  wk:4%")
        self.assertEqual(got["badge"], "opus 5 · high")

    def test_an_agent_with_no_cached_statusline_keeps_its_own_values(self):
        agent = {"pane_id": "w2:p1", "agent": "codex"}
        got = badge.tokens_for(
            agent,
            resolve=lambda kind: fake_reader({"model": "gpt 5.5", "ctx": "17k"}),
            cache=self.cache,
        )
        self.assertEqual(got["ctx"], "17k")
        self.assertIsNone(got["usage"])
