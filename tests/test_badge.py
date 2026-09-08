"""Turning one herdr AgentInfo into the token set we report back to herdr."""

import unittest

from herdr_model_badge import SOURCE, USAGE_SOURCE, badge, usage

TOKEN_NAMES = ("badge", "model", "effort", "perm", "ctx", "ctx_num", "cost", "usage",
               "usage_session", "usage_session_pct", "usage_session_at",
               "usage_session_label", "usage_session_num",
               "usage_period", "usage_period_pct", "usage_period_at",
               "usage_period_label", "usage_period_num")


class NoCache:
    """Stands in for the statusline cache in tests that are not about it."""

    @staticmethod
    def read(pane_id, session_id, now=None):
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
        import time

        # A cached reading carries the moment it stops counting, so a recent one
        # still overlays the transcript on a later event.
        self.cache.write("w1:p1", "sess-1", {
            "ctx": "6%",
            "usage": "5h:6%  wk:4%",
            usage.EXPIRES_KEY: time.time() + 600,
        })
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


class ReportsForTests(unittest.TestCase):
    """One reading, two reports: what lasts and what a clock invalidates."""

    WINDOW = {"minutes": 300, "percent": 6, "resets_at": None}

    def reader(self):
        values = {"model": "opus 5", "effort": "high", "ctx": "6%", "ctx_num": "6",
                  "cost": "$1.23"}
        values.update(usage.tokens([self.WINDOW]))
        return fake_reader(values)

    def reports(self):
        agent = {"pane_id": "w1:p1", "agent": "claude"}
        return badge.reports_for(agent, resolve=lambda kind: self.reader(), cache=NO_CACHE)

    def test_the_number_a_rule_can_compare_travels_with_the_value_it_styles(self):
        # ctx_num is durable for the same reason ctx is: only the agent moves it.
        durable, ephemeral = self.reports()
        self.assertIn("ctx_num", durable.tokens)
        self.assertIn("usage_session_num", ephemeral.tokens)

    def test_the_durable_values_go_out_without_a_ttl(self):
        durable = self.reports()[0]
        self.assertEqual(durable.source, SOURCE)
        self.assertIsNone(durable.ttl_ms)
        self.assertEqual(durable.tokens["badge"], "opus 5 · high")
        self.assertEqual(durable.tokens["cost"], "$1.23")
        self.assertEqual(durable.tokens["ctx"], "6%")
        self.assertNotIn("usage", durable.tokens)

    def test_the_usage_values_go_out_under_their_own_source_with_a_ttl(self):
        ephemeral = self.reports()[1]
        self.assertEqual(ephemeral.source, USAGE_SOURCE)
        self.assertEqual(ephemeral.tokens["usage_session_pct"], "5h:6%")
        self.assertEqual(ephemeral.tokens["usage_session_num"], "6")
        self.assertEqual(ephemeral.tokens["usage_session_label"], "5h")
        self.assertGreater(ephemeral.ttl_ms, 0)
        self.assertNotIn("model", ephemeral.tokens)

    def test_the_internal_expiry_is_never_reported_as_a_token(self):
        for report in self.reports():
            self.assertNotIn(usage.EXPIRES_KEY, report.tokens)

    def test_an_agent_with_no_usage_asks_for_no_ttl(self):
        agent = {"pane_id": "w1:p1", "agent": "claude"}
        durable, ephemeral = badge.reports_for(
            agent, resolve=lambda kind: fake_reader({"model": "opus 5"}), cache=NO_CACHE
        )
        self.assertIsNone(ephemeral.ttl_ms)
        self.assertTrue(all(value is None for value in ephemeral.tokens.values()))

    def test_between_them_the_reports_cover_every_token_exactly_once(self):
        names = [name for report in self.reports() for name in report.tokens]
        self.assertEqual(sorted(names), sorted(badge.TOKEN_NAMES))


class TokenBudgetTests(unittest.TestCase):
    def test_each_report_fits_what_one_call_can_carry(self):
        # pane.report_metadata caps tokens at 16 per call. The two groups exceed
        # that together, which is why nothing ever sends their union.
        self.assertLessEqual(len(badge.DURABLE_TOKENS), 16)
        self.assertLessEqual(len(badge.EPHEMERAL_TOKENS), 16)

    def test_the_groups_do_not_overlap(self):
        self.assertEqual(
            set(badge.DURABLE_TOKENS) & set(badge.EPHEMERAL_TOKENS), set()
        )

    def test_token_names_are_valid_herdr_identifiers(self):
        import re

        for name in badge.TOKEN_NAMES:
            self.assertRegex(name, r"^[A-Za-z0-9_-]{1,32}$")
