"""Reading Claude Code's statusLine payload, and the cache that outlives it."""

import datetime
import json
import os
import tempfile
import unittest

from herdr_model_badge import statusline


def at(text):
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


NOW = at("2026-09-07 23:50")

PAYLOAD = {
    "session_id": "sess-1",
    "model": {"display_name": "Opus 5"},
    "effort": {"level": "high"},
    "context_window": {"used_percentage": 6.4},
    "rate_limits": {
        "five_hour": {"used_percentage": 6, "resets_at": at("2026-09-08 04:29")},
        "seven_day": {"used_percentage": 4, "resets_at": at("2026-09-13 23:59")},
    },
}


class ValuesTests(unittest.TestCase):
    def test_context_percentage_and_both_usage_windows(self):
        got = statusline.values(PAYLOAD, now=NOW)
        self.assertEqual(got["ctx"], "6%")
        self.assertEqual(got["usage_session"], "5h:6% (→04:29)")
        self.assertEqual(got["usage_period"], "wk:4% (→09-13)")
        self.assertEqual(got["usage"], "5h:6%  wk:4%")

    def test_model_and_effort_come_through_as_fallbacks(self):
        got = statusline.values(PAYLOAD, now=NOW)
        self.assertEqual(got["model"], "opus 5")
        self.assertEqual(got["effort"], "high")

    def test_a_plan_without_subscription_limits_reports_no_usage(self):
        payload = dict(PAYLOAD)
        payload.pop("rate_limits")
        got = statusline.values(payload, now=NOW)
        self.assertEqual(got["ctx"], "6%")
        for name in ("usage", "usage_session", "usage_period"):
            self.assertNotIn(name, got)

    def test_a_window_that_already_reset_is_dropped(self):
        payload = json.loads(json.dumps(PAYLOAD))
        payload["rate_limits"]["five_hour"]["resets_at"] = at("2026-09-07 07:29")
        got = statusline.values(payload, now=NOW)
        self.assertNotIn("usage_session", got)
        self.assertEqual(got["usage_period"], "wk:4% (→09-13)")

    def test_context_percentage_is_absent_before_the_first_api_response(self):
        payload = json.loads(json.dumps(PAYLOAD))
        payload["context_window"] = {"used_percentage": None}
        self.assertNotIn("ctx", statusline.values(payload, now=NOW))

    def test_junk_payloads_yield_nothing(self):
        for payload in ({}, None, [], "text"):
            self.assertEqual(statusline.values(payload, now=NOW), {})

    def test_session_id_is_lifted_out_for_cache_validation(self):
        self.assertEqual(statusline.session_id_of(PAYLOAD), "sess-1")
        self.assertIsNone(statusline.session_id_of({}))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = statusline.Cache(self.tmp.name)

    def test_a_written_entry_reads_back(self):
        self.cache.write("w1:p1", "sess-1", {"ctx": "6%"})
        self.assertEqual(self.cache.read("w1:p1", "sess-1"), {"ctx": "6%"})

    def test_a_pane_id_with_a_colon_is_still_one_file(self):
        self.cache.write("w1:p1", "sess-1", {"ctx": "6%"})
        self.assertEqual(len(os.listdir(self.tmp.name)), 1)

    def test_a_different_session_does_not_inherit_the_entry(self):
        # The pane was reused by another agent run; its usage is not ours.
        self.cache.write("w1:p1", "sess-1", {"ctx": "6%"})
        self.assertEqual(self.cache.read("w1:p1", "sess-2"), {})

    def test_an_entry_written_without_a_session_is_readable_by_any_session(self):
        self.cache.write("w1:p1", None, {"ctx": "6%"})
        self.assertEqual(self.cache.read("w1:p1", "sess-9"), {"ctx": "6%"})

    def test_a_missing_entry_is_empty(self):
        self.assertEqual(self.cache.read("w9:p9", "sess-1"), {})

    def test_a_corrupt_entry_is_empty_rather_than_fatal(self):
        self.cache.write("w1:p1", "sess-1", {"ctx": "6%"})
        path = os.path.join(self.tmp.name, os.listdir(self.tmp.name)[0])
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{ truncated")
        self.assertEqual(self.cache.read("w1:p1", "sess-1"), {})

    def test_an_unwritable_cache_does_not_raise(self):
        cache = statusline.Cache(os.path.join(self.tmp.name, "file-in-the-way", "deeper"))
        with open(os.path.join(self.tmp.name, "file-in-the-way"), "w") as handle:
            handle.write("x")
        cache.write("w1:p1", "sess-1", {"ctx": "6%"})
        self.assertEqual(cache.read("w1:p1", "sess-1"), {})

    def test_writing_twice_replaces_rather_than_appends(self):
        self.cache.write("w1:p1", "sess-1", {"ctx": "6%"})
        self.cache.write("w1:p1", "sess-1", {"ctx": "9%"})
        self.assertEqual(self.cache.read("w1:p1", "sess-1"), {"ctx": "9%"})
        self.assertEqual(len(os.listdir(self.tmp.name)), 1)


if __name__ == "__main__":
    unittest.main()


class StateDirTests(unittest.TestCase):
    def setUp(self):
        self.saved = {
            name: os.environ.get(name)
            for name in ("HERDR_PLUGIN_STATE_DIR", "XDG_STATE_HOME", "HOME")
        }
        self.addCleanup(self.restore)

    def restore(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_herdrs_own_value_is_used_when_it_is_given(self):
        os.environ["HERDR_PLUGIN_STATE_DIR"] = "/state/from/herdr"
        self.assertEqual(statusline.default_state_dir(), "/state/from/herdr")

    def test_without_it_the_same_directory_is_derived(self):
        # The statusline runs from Claude Code, which passes no HERDR_PLUGIN_* vars,
        # so this must land on the directory herdr would have named.
        os.environ.pop("HERDR_PLUGIN_STATE_DIR", None)
        os.environ["XDG_STATE_HOME"] = "/home/someone/.local/state"
        self.assertEqual(
            statusline.default_state_dir(),
            "/home/someone/.local/state/herdr/plugins/herdr-model-badge",
        )

    def test_it_falls_back_to_the_home_directory_layout(self):
        os.environ.pop("HERDR_PLUGIN_STATE_DIR", None)
        os.environ.pop("XDG_STATE_HOME", None)
        os.environ["HOME"] = "/home/someone"
        self.assertEqual(
            statusline.default_state_dir(),
            "/home/someone/.local/state/herdr/plugins/herdr-model-badge",
        )
