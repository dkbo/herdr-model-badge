"""Pi's reported session, model switches and append-only branch history."""

import json
import os
import tempfile
import unittest
from unittest import mock

from herdr_model_badge import badge, providers
from herdr_model_badge.providers import pi


def entry(kind, identifier, parent=None, **fields):
    return dict(type=kind, id=identifier, parentId=parent, **fields)


def model(identifier="model", parent=None, name="claude-sonnet-4-5"):
    return entry("model_change", identifier, parent, provider="anthropic", modelId=name)


def thinking(identifier="thinking", parent="model", level="high"):
    return entry("thinking_level_change", identifier, parent, thinkingLevel=level)


def assistant(identifier="answer", parent="thinking", **fields):
    message = dict(role="assistant", model="claude-sonnet-4-5", thinkingLevel="high")
    message.update(fields)
    return entry("message", identifier, parent, message=message)


class PiProviderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.path = os.path.join(self.home, "sessions", "--project--", "2026-01-01_sess-1.jsonl")
        os.makedirs(os.path.dirname(self.path))

    def write(self, rows):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "session", "version": 3,
                                     "id": "sess-1", "cwd": "/project"}) + "\n")
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return self.path

    def read(self):
        return pi.read({"session_path": self.path}, home=self.home)

    def test_pi_is_registered(self):
        self.assertIs(providers.for_agent("pi"), pi.read)

    def test_reads_selection_before_the_first_response(self):
        self.write([model(), thinking()])
        self.assertEqual(self.read(), {"model": "sonnet 4.5", "effort": "high"})

    def test_reported_path_takes_precedence_over_session_search(self):
        self.write([model(), thinking()])
        got = pi.read({"session_path": self.path, "session_id": "unknown"}, home=self.home)
        self.assertEqual(got["model"], "sonnet 4.5")

    def test_finds_an_exact_reported_session_id(self):
        self.write([model(), thinking()])
        self.assertEqual(pi.read({"session_id": "sess-1"}, home=self.home), self.read())

    def test_missing_identity_does_not_guess_between_sessions_in_the_same_cwd(self):
        self.write([model(), thinking()])
        self.assertEqual(pi.read({"cwd": "/project"}, home=self.home), {})
        self.assertEqual(pi.read({"session_id": "stale", "cwd": "/project"}, home=self.home), {})

    def test_session_id_is_not_a_glob(self):
        self.write([model(), thinking()])
        self.assertEqual(pi.read({"session_id": "*"}, home=self.home), {})

    def test_custom_agent_directory_is_honoured(self):
        self.write([model(), thinking()])
        with mock.patch.dict(os.environ, {"PI_CODING_AGENT_DIR": self.home}):
            self.assertEqual(pi.read({"session_id": "sess-1"}), self.read())

    def test_default_agent_directory(self):
        with mock.patch.dict(os.environ, {"HOME": self.home, "PI_CODING_AGENT_DIR": ""}):
            self.assertEqual(pi.default_home(), os.path.join(self.home, ".pi", "agent"))

    def test_newer_assistant_metadata_is_read_without_initial_markers(self):
        self.write([assistant(parent=None, model="gpt-5.5", thinkingLevel="xhigh")])
        self.assertEqual(self.read(), {"model": "gpt 5.5", "effort": "xhigh"})

    def test_switches_after_an_assistant_response_override_that_response(self):
        self.write([model(), thinking(), assistant(),
                    model("next", "answer", "gpt-5.5"), thinking("effort", "next", "low")])
        self.assertEqual(self.read(), {"model": "gpt 5.5", "effort": "low"})

    def test_thinking_off_is_a_real_value(self):
        self.write([model(), thinking(level="off")])
        self.assertEqual(self.read()["effort"], "off")

    def test_old_assistant_messages_inherit_the_recorded_thinking_level(self):
        answer = assistant()
        answer["message"].pop("thinkingLevel")
        self.write([model(), thinking(), answer])
        self.assertEqual(self.read(), {"model": "sonnet 4.5", "effort": "high"})

    def test_settings_from_an_abandoned_branch_are_ignored(self):
        answer = assistant("continued", "thinking")
        answer["message"].pop("thinkingLevel")
        self.write([model(), thinking(), model("other-model", "thinking", "gpt-5.5"),
                    thinking("other-effort", "other-model", "low"), answer])
        self.assertEqual(self.read(), {"model": "sonnet 4.5", "effort": "high"})

    def test_a_new_root_does_not_inherit_settings_from_the_old_tree(self):
        self.write([model(), thinking(), model("root", None, "gpt-5.5")])
        self.assertEqual(self.read(), {"model": "gpt 5.5"})

    def test_tool_results_and_extension_metadata_are_not_model_selections(self):
        self.write([model(), thinking(),
                    entry("message", "tool", "thinking", message={"role": "toolResult", "model": "wrong"}),
                    entry("custom", "extension", "tool", data={"model": "wrong"})])
        self.assertEqual(self.read(), {"model": "sonnet 4.5", "effort": "high"})

    def test_missing_or_empty_session_yields_nothing(self):
        self.assertEqual(self.read(), {})
        self.write([])
        self.assertEqual(self.read(), {})

    def test_malformed_lines_are_skipped(self):
        self.write([model(), thinking()])
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write('null\n[]\n{broken\n')
        self.assertEqual(self.read(), {"model": "sonnet 4.5", "effort": "high"})

    def test_settings_behind_the_normal_tail_are_found_with_one_escalation(self):
        self.write([model(), thinking(),
                    entry("custom", "large", "thinking", data="x" * 300_000)])
        self.assertEqual(self.read(), {"model": "sonnet 4.5", "effort": "high"})

    def test_new_assistant_metadata_avoids_escalating_large_sessions(self):
        self.write([model(), thinking(),
                    entry("custom", "large", "thinking", data="x" * 300_000),
                    assistant(parent="large")])
        with mock.patch.object(pi, "_settings", wraps=pi._settings) as scan:
            self.assertEqual(self.read(), {"model": "sonnet 4.5", "effort": "high"})
        self.assertEqual(scan.call_count, 1)

    def test_unreachable_settings_are_not_guessed_from_other_branches(self):
        self.write([model(), thinking(),
                    entry("custom", "large", "thinking", data="x" * (pi.SETTINGS_TAIL_BYTES + 1)),
                    model("other", "large", "gpt-5.5"),
                    entry("custom", "continued", "thinking")])
        self.assertEqual(self.read(), {})

    def test_model_only_does_not_invent_effort_or_usage(self):
        self.write([model()])
        self.assertEqual(self.read(), {"model": "sonnet 4.5"})

    def test_real_agent_info_produces_a_composed_badge(self):
        self.write([model(), thinking()])
        agent = {"agent": "pi", "agent_session": {"kind": "path", "value": self.path}}
        got = badge.tokens_for(agent)
        self.assertEqual(got["badge"], "sonnet 4.5 · high")
        self.assertIsNone(got["ctx"])
        self.assertIsNone(got["cost"])


if __name__ == "__main__":
    unittest.main()
