"""The three modes, driven against a fake herdr client."""

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
