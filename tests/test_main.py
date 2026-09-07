"""The four modes, driven against a fake herdr client."""

import io
import json
import os
import unittest

from herdr_model_badge import __main__ as cli
from herdr_model_badge.api import HerdrError


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

    def report(self, pane_id, source, tokens):
        self.reports.append((pane_id, source, tokens))
        return {}

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


class SweepTests(unittest.TestCase):
    def test_a_stale_badge_on_an_unreadable_agent_is_cleared(self):
        client = FakeClient([STALE_PANE])
        self.assertEqual(cli.sweep(client), 1)
        pane_id, source, tokens = client.reports[0]
        self.assertEqual(pane_id, "w2:p1")
        self.assertEqual(source, "herdr-model-badge")
        self.assertTrue(all(value is None for value in tokens.values()))

    def test_an_agent_already_showing_the_right_tokens_is_left_alone(self):
        client = FakeClient([FRESH_PANE, dict(STALE_PANE, tokens={})])
        self.assertEqual(cli.sweep(client), 0)
        self.assertEqual(client.reports, [])

    def test_one_failing_pane_does_not_abort_the_sweep(self):
        class Flaky(FakeClient):
            def report(self, pane_id, source, tokens):
                if pane_id == "w1:p1":
                    raise HerdrError("pane.report_metadata", {"code": "pane_not_found"})
                return super().report(pane_id, source, tokens)

        client = Flaky([dict(STALE_PANE, pane_id="w1:p1"), STALE_PANE])
        self.assertEqual(cli.sweep(client), 1)
        self.assertEqual([report[0] for report in client.reports], ["w2:p1"])


class EventTests(unittest.TestCase):
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
        pane_id, _, tokens = client.reports[0]
        self.assertEqual(pane_id, "w9:p1")
        self.assertTrue(all(value is None for value in tokens.values()))

    def test_an_event_without_a_pane_id_does_nothing(self):
        client = FakeClient([STALE_PANE])
        self.assertEqual(self.run_event(client, "{}"), 0)
        self.assertEqual(client.reports, [])


class ClearTests(unittest.TestCase):
    def test_panes_holding_our_tokens_are_cleared(self):
        client = FakeClient([STALE_PANE])
        self.assertEqual(cli.clear(client), 1)
        self.assertTrue(all(value is None for value in client.reports[0][2].values()))

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
