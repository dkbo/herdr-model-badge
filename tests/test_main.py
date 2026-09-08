"""The four modes, driven against a fake herdr client."""

import collections
import io
import json
import os
import tempfile
import time
import unittest

from herdr_model_badge import SOURCE, USAGE_SOURCE
from herdr_model_badge import __main__ as cli
from herdr_model_badge.api import HerdrError


Report = collections.namedtuple("Report", "pane_id source tokens ttl_ms")


class IsolatedState(unittest.TestCase):
    """Point the statusline cache at a temporary directory.

    The cache is keyed by pane id, so a test naming a pane that the developer's own
    machine happens to have cached would read that real entry back and fail only on
    that machine.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        homes = {
            "HERDR_PLUGIN_STATE_DIR": self.tmp.name,
            "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude"),
            "CODEX_HOME": os.path.join(self.tmp.name, "codex"),
        }
        previous = {name: os.environ.get(name) for name in homes}
        os.environ.update(homes)

        def restore():
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.addCleanup(restore)


class FakeClient:
    def __init__(self, agents=(), failing_panes=()):
        self._agents = list(agents)
        self._failing = set(failing_panes)
        self.reports = []
        self.notifications = []

    def available(self):
        return True

    def agents(self):
        return list(self._agents)

    def agent(self, pane_id):
        if pane_id in self._failing:
            raise HerdrError("agent.get", {"code": "pane_not_found"})
        for agent in self._agents:
            if agent.get("pane_id") == pane_id:
                return dict(agent)
        raise HerdrError("agent.get", {"code": "pane_not_found"})

    def report(self, pane_id, source, tokens, ttl_ms=None):
        self.reports.append(Report(pane_id, source, tokens, ttl_ms))
        return {}

    def reports_from(self, source):
        return [report for report in self.reports if report.source == source]

    def notify(self, title, body=None):
        self.notifications.append((title, body))
        return {}


# An agent we cannot read, still carrying a badge from whatever used to occupy the
# pane. Clearing it is the only report a provider-less agent ever needs.
STALE_PANE = {
    "pane_id": "w2:p1",
    "agent": "cursor",
    "tokens": {"badge": "opus 5 · high", "model": "opus 5"},
}
FRESH_PANE = {"pane_id": "w3:p1", "agent": "cursor"}


class EventPaneIdTests(unittest.TestCase):
    def test_pane_id_is_read_from_the_event_envelope(self):
        raw = '{"event":"pane_agent_status_changed","data":{"pane_id":"w1:p1"}}'
        self.assertEqual(cli.event_pane_id(raw), "w1:p1")

    def test_a_flat_payload_also_works(self):
        self.assertEqual(cli.event_pane_id('{"pane_id":"w1:p2"}'), "w1:p2")

    def test_unusable_payloads_yield_no_pane(self):
        for raw in (None, "", "not json", "{}", '{"data":{}}', '{"pane_id":7}', "[]"):
            self.assertIsNone(cli.event_pane_id(raw), raw)


class SweepTests(IsolatedState):
    def test_a_stale_badge_on_an_unreadable_agent_is_cleared(self):
        client = FakeClient([STALE_PANE])
        self.assertEqual(cli.sweep(client), 1)
        report = client.reports[0]
        self.assertEqual(report.pane_id, "w2:p1")
        self.assertEqual(report.source, "herdr-model-badge")
        self.assertTrue(all(value is None for value in report.tokens.values()))

    def test_an_agent_already_showing_the_right_tokens_is_left_alone(self):
        client = FakeClient([FRESH_PANE, dict(STALE_PANE, tokens={})])
        self.assertEqual(cli.sweep(client), 0)
        self.assertEqual(client.reports, [])

    def test_one_failing_pane_does_not_abort_the_sweep(self):
        class Flaky(FakeClient):
            def report(self, pane_id, source, tokens, ttl_ms=None):
                if pane_id == "w1:p1":
                    raise HerdrError("pane.report_metadata", {"code": "pane_not_found"})
                return super().report(pane_id, source, tokens, ttl_ms)

        client = Flaky([dict(STALE_PANE, pane_id="w1:p1"), STALE_PANE])
        self.assertEqual(cli.sweep(client), 1)
        self.assertEqual([report[0] for report in client.reports], ["w2:p1"])


class EventTests(IsolatedState):
    def run_event(self, client, raw):
        import os

        previous = os.environ.get("HERDR_PLUGIN_EVENT_JSON")
        if raw is None:
            os.environ.pop("HERDR_PLUGIN_EVENT_JSON", None)
        else:
            os.environ["HERDR_PLUGIN_EVENT_JSON"] = raw
        try:
            return cli.event(client)
        finally:
            if previous is None:
                os.environ.pop("HERDR_PLUGIN_EVENT_JSON", None)
            else:
                os.environ["HERDR_PLUGIN_EVENT_JSON"] = previous

    def test_only_the_named_pane_is_touched(self):
        client = FakeClient([STALE_PANE, dict(STALE_PANE, pane_id="w3:p1")])
        self.assertEqual(self.run_event(client, '{"data":{"pane_id":"w2:p1"}}'), 1)
        self.assertEqual([report[0] for report in client.reports], ["w2:p1"])

    def test_a_pane_that_lost_its_agent_gets_its_tokens_cleared(self):
        client = FakeClient([], failing_panes=["w9:p1"])
        self.assertEqual(self.run_event(client, '{"data":{"pane_id":"w9:p1"}}'), 1)
        self.assertEqual(client.reports[0].pane_id, "w9:p1")
        for report in client.reports:
            self.assertTrue(all(value is None for value in report.tokens.values()))

    def test_an_event_without_a_pane_id_does_nothing(self):
        client = FakeClient([STALE_PANE])
        self.assertEqual(self.run_event(client, "{}"), 0)
        self.assertEqual(client.reports, [])


class TwoSourceTests(IsolatedState):
    """Usage goes out under its own source so herdr can expire it on its own."""

    PANE = {
        "pane_id": "w1:p1",
        "agent": "claude",
        "agent_session": {"kind": "id", "value": "sess-1"},
    }
    PAYLOAD = json.dumps(
        {
            "session_id": "sess-1",
            "context_window": {"used_percentage": 6},
            "cost": {"total_cost_usd": 1.2345},
            "rate_limits": {
                "five_hour": {"used_percentage": 6, "resets_at": time.time() + 3600},
            },
        }
    )

    def seed_statusline(self):
        """Give the pane a reading only the statusline could have seen."""
        from herdr_model_badge import statusline

        payload = json.loads(self.PAYLOAD)
        cache = statusline.Cache(self.tmp.name)
        cache.write("w1:p1", "sess-1", statusline.values(payload))
        return statusline.values(payload)

    def test_each_source_carries_its_own_half_of_the_reading(self):
        self.seed_statusline()
        client = FakeClient([self.PANE])
        self.assertEqual(cli.sweep(client), 1)

        durable = client.reports_from(SOURCE)[0]
        self.assertEqual(durable.tokens["ctx"], "6%")
        self.assertEqual(durable.tokens["cost"], "$1.23")
        self.assertIsNone(durable.ttl_ms)

        ephemeral = client.reports_from(USAGE_SOURCE)[0]
        self.assertEqual(ephemeral.tokens["usage_session_pct"], "5h:6%")
        self.assertGreater(ephemeral.ttl_ms, 0)
        self.assertLessEqual(ephemeral.ttl_ms, 86_400_000)

    def test_a_pane_with_nothing_to_expire_is_sent_no_usage_report(self):
        client = FakeClient([dict(self.PANE, tokens={"model": "opus 5"})])
        cli.sweep(client)
        self.assertEqual(client.reports_from(USAGE_SOURCE), [])

    def test_an_unchanged_usage_reading_is_still_resent_to_rearm_its_ttl(self):
        # herdr drops the tokens when the ttl runs out, so a pane that keeps working
        # without moving the needle must keep saying so or the row would blink empty.
        seen = self.seed_statusline()
        settled = dict(self.PANE, tokens=dict(seen))
        settled["tokens"]["badge"] = None
        client = FakeClient([settled])
        cli.apply_to(client, settled, arm_usage=True)
        self.assertEqual(len(client.reports_from(USAGE_SOURCE)), 1)

    def test_the_statusline_path_does_not_rearm_on_every_render(self):
        seen = self.seed_statusline()
        settled = dict(self.PANE, tokens=dict(seen))
        settled["tokens"]["badge"] = None
        client = FakeClient([settled])
        cli.apply_to(client, settled)
        self.assertEqual(client.reports_from(USAGE_SOURCE), [])


class ClearTests(IsolatedState):
    def test_panes_holding_our_tokens_are_cleared(self):
        client = FakeClient([STALE_PANE])
        self.assertEqual(cli.clear(client), 1)
        self.assertTrue(all(value is None for value in client.reports[0][2].values()))

    def test_no_cleared_report_exceeds_what_herdr_accepts(self):
        client = FakeClient([dict(STALE_PANE, tokens={"model": "opus 5", "usage": "5h:6%"})])
        cli.clear(client)
        for report in client.reports:
            self.assertLessEqual(len(report.tokens), 16)
            self.assertTrue(all(value is None for value in report.tokens.values()))

    def test_clearing_names_exactly_the_tokens_its_source_reports(self):
        from herdr_model_badge import badge

        client = FakeClient([dict(STALE_PANE, tokens={"model": "opus 5", "usage": "5h:6%"})])
        cli.clear(client)
        sent = {report.source: sorted(report.tokens) for report in client.reports}
        self.assertEqual(sent[SOURCE], sorted(badge.DURABLE_TOKENS))
        self.assertEqual(sent[USAGE_SOURCE], sorted(badge.EPHEMERAL_TOKENS))

    def test_both_sources_are_cleared(self):
        client = FakeClient([dict(STALE_PANE, tokens={"model": "opus 5", "usage": "5h:6%"})])
        self.assertEqual(cli.clear(client), 1)
        self.assertEqual(
            sorted(report.source for report in client.reports),
            sorted([SOURCE, USAGE_SOURCE]),
        )

    def test_panes_with_nothing_of_ours_are_left_alone(self):
        client = FakeClient([dict(STALE_PANE, tokens={"jj_status": "dirty"})])
        self.assertEqual(cli.clear(client), 0)
        self.assertEqual(client.reports, [])


if __name__ == "__main__":
    unittest.main()


class StatuslineModeTests(unittest.TestCase):
    """The wrapper's contract: report if you can, but always render the statusline."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {}
        for name in ("HERDR_PANE_ID", "HERDR_SOCKET_PATH", "HERDR_PLUGIN_STATE_DIR"):
            self.env[name] = os.environ.get(name)
        os.environ["HERDR_PLUGIN_STATE_DIR"] = self.tmp.name
        os.environ.pop("HERDR_SOCKET_PATH", None)
        self.addCleanup(self.restore)

    def restore(self):
        for name, value in self.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    @staticmethod
    def invoke(argv, payload="{}"):
        return cli.main(argv, stdin=io.StringIO(payload))

    def test_the_wrapped_command_still_runs_and_reports_success(self):
        self.assertEqual(self.invoke(["statusline", "--", "true"]), 0)

    def test_the_wrapped_command_receives_the_same_payload_on_stdin(self):
        # A statusline reads its JSON from stdin, so the wrapper must replay it.
        marker = os.path.join(self.tmp.name, "seen.json")
        rc = self.invoke(
            ["statusline", "--", "sh", "-c", "cat > %s" % marker],
            payload='{"session_id":"sess-1"}',
        )
        self.assertEqual(rc, 0)
        with open(marker, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["session_id"], "sess-1")

    def test_the_wrapped_commands_exit_code_is_preserved(self):
        self.assertEqual(self.invoke(["statusline", "--", "sh", "-c", "exit 3"]), 3)

    def test_a_missing_wrapped_command_is_reported_not_raised(self):
        self.assertEqual(self.invoke(["statusline", "--", "definitely-not-a-command"]), 0)

    def test_an_unparsable_payload_still_renders_the_statusline(self):
        self.assertEqual(self.invoke(["statusline", "--", "true"], payload="not json"), 0)

    def test_no_wrapped_command_is_allowed(self):
        self.assertEqual(self.invoke(["statusline"]), 0)


class StatuslineReportingTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        from herdr_model_badge import statusline

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.previous = os.environ.get("HERDR_PLUGIN_STATE_DIR")
        os.environ["HERDR_PLUGIN_STATE_DIR"] = self.tmp.name
        self.addCleanup(self.restore)
        self.cache = statusline.Cache(self.tmp.name)
        self.pane = os.environ.get("HERDR_PANE_ID")
        os.environ["HERDR_PANE_ID"] = "w1:p1"

    def restore(self):
        if self.previous is None:
            os.environ.pop("HERDR_PLUGIN_STATE_DIR", None)
        else:
            os.environ["HERDR_PLUGIN_STATE_DIR"] = self.previous
        if self.pane is None:
            os.environ.pop("HERDR_PANE_ID", None)
        else:
            os.environ["HERDR_PANE_ID"] = self.pane

    PAYLOAD = json.dumps(
        {
            "session_id": "sess-1",
            "context_window": {"used_percentage": 6},
            "model": {"display_name": "Opus 5"},
        }
    )

    def test_a_first_payload_is_cached_and_reported(self):
        client = FakeClient([{"pane_id": "w1:p1", "agent": "claude"}])
        self.assertEqual(cli.statusline_mode(client, [], self.PAYLOAD), 1)
        self.assertEqual(self.cache.read("w1:p1", "sess-1")["ctx"], "6%")
        self.assertEqual(client.reports[0][2]["ctx"], "6%")

    def test_an_unchanged_payload_never_touches_the_socket(self):
        client = FakeClient([{"pane_id": "w1:p1", "agent": "claude"}])
        cli.statusline_mode(client, [], self.PAYLOAD)
        client.reports.clear()
        self.assertEqual(cli.statusline_mode(client, [], self.PAYLOAD), 0)
        self.assertEqual(client.reports, [])

    def test_an_unparsable_payload_is_ignored(self):
        client = FakeClient([{"pane_id": "w1:p1", "agent": "claude"}])
        self.assertEqual(cli.statusline_mode(client, [], "not json"), 0)
        self.assertEqual(client.reports, [])

    def test_running_outside_a_herdr_pane_does_nothing(self):
        os.environ.pop("HERDR_PANE_ID", None)
        client = FakeClient([])
        self.assertEqual(cli.statusline_mode(client, [], self.PAYLOAD), 0)


class LauncherModeTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = {
            name: os.environ.get(name)
            for name in ("HERDR_PLUGIN_STATE_DIR", "HERDR_PLUGIN_ROOT")
        }
        os.environ["HERDR_PLUGIN_STATE_DIR"] = self.tmp.name
        os.environ["HERDR_PLUGIN_ROOT"] = "/plugins/here"
        self.addCleanup(self.restore)

    def restore(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_a_sweep_also_refreshes_the_launcher(self):
        client = FakeClient([])
        cli.sweep(client)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "statusline")))

    def test_the_launcher_points_at_the_root_herdr_reported(self):
        cli.write_launcher()
        with open(os.path.join(self.tmp.name, "statusline"), encoding="utf-8") as handle:
            self.assertIn("PYTHONPATH='/plugins/here'", handle.read())
