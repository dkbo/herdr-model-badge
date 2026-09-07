"""Each provider turns one agent's own session log into display-ready values."""

import json
import os
import tempfile
import unittest

from herdr_model_badge import providers
from herdr_model_badge.providers import agy, claude, codex


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return path


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name


CLAUDE_ASSISTANT = {
    "type": "assistant",
    "effort": "high",
    "message": {
        "model": "claude-opus-5",
        "usage": {
            "input_tokens": 2,
            "cache_creation_input_tokens": 376,
            "cache_read_input_tokens": 103894,
            "output_tokens": 243,
        },
    },
}


class ClaudeProviderTests(TempHome):
    def transcript(self, rows, session_id="sess-1", project="-home-bal-project-x"):
        return write_jsonl(
            os.path.join(self.home, "projects", project, session_id + ".jsonl"), rows
        )

    def test_reads_model_effort_permission_and_context(self):
        self.transcript(
            [
                {"type": "user", "permissionMode": "acceptEdits"},
                CLAUDE_ASSISTANT,
            ]
        )
        got = claude.read({"session_id": "sess-1"}, home=self.home)
        self.assertEqual(got["model"], "opus 5")
        self.assertEqual(got["effort"], "high")
        self.assertEqual(got["perm"], "accept edits")
        self.assertEqual(got["ctx"], "104k")

    def test_newest_assistant_entry_wins(self):
        older = json.loads(json.dumps(CLAUDE_ASSISTANT))
        older["effort"] = "low"
        older["message"]["model"] = "claude-haiku-4-5"
        self.transcript([older, CLAUDE_ASSISTANT])
        got = claude.read({"session_id": "sess-1"}, home=self.home)
        self.assertEqual(got["model"], "opus 5")
        self.assertEqual(got["effort"], "high")

    def test_a_reported_session_path_is_preferred_over_searching(self):
        path = write_jsonl(os.path.join(self.home, "elsewhere.jsonl"), [CLAUDE_ASSISTANT])
        got = claude.read({"session_id": "absent", "session_path": path}, home=self.home)
        self.assertEqual(got["model"], "opus 5")

    def test_subagent_sidechain_entries_are_ignored(self):
        # A sidechain turn can run a different model; the pane shows the main agent.
        sidechain = json.loads(json.dumps(CLAUDE_ASSISTANT))
        sidechain["isSidechain"] = True
        sidechain["message"]["model"] = "claude-haiku-4-5"
        self.transcript([CLAUDE_ASSISTANT, sidechain])
        got = claude.read({"session_id": "sess-1"}, home=self.home)
        self.assertEqual(got["model"], "opus 5")

    def test_transcript_without_an_assistant_turn_yields_nothing_readable(self):
        self.transcript([{"type": "user"}])
        self.assertEqual(claude.read({"session_id": "sess-1"}, home=self.home), {})

    def test_a_stale_session_id_falls_back_to_the_newest_log_for_the_cwd(self):
        # herdr keeps the id from SessionStart; a resume writes a new transcript.
        resumed = json.loads(json.dumps(CLAUDE_ASSISTANT))
        resumed["cwd"] = "/home/bal/project/x"
        resumed["message"]["model"] = "claude-fable-5-1"
        self.transcript([resumed], session_id="resumed")
        got = claude.read(
            {"session_id": "stale", "cwd": "/home/bal/project/x"}, home=self.home
        )
        self.assertEqual(got["model"], "fable 5.1")

    def test_the_fallback_ignores_logs_belonging_to_another_cwd(self):
        other = json.loads(json.dumps(CLAUDE_ASSISTANT))
        other["cwd"] = "/home/bal/project/other"
        self.transcript([other], session_id="other", project="-home-bal-project-other")
        got = claude.read(
            {"session_id": "stale", "cwd": "/home/bal/project/x"}, home=self.home
        )
        self.assertEqual(got, {})

    def test_unknown_session_and_unknown_cwd_yield_nothing_readable(self):
        self.transcript([CLAUDE_ASSISTANT])
        self.assertEqual(claude.read({"session_id": "ghost"}, home=self.home), {})

    def test_missing_session_id_yields_nothing_readable(self):
        self.assertEqual(claude.read({}, home=self.home), {})

    def test_a_session_with_only_the_change_marker_still_reports_the_mode(self):
        # The standalone marker is written on change; some sessions have no user
        # turn carrying the mode at all.
        self.transcript(
            [{"type": "permission-mode", "permissionMode": "plan"}, CLAUDE_ASSISTANT]
        )
        got = claude.read({"session_id": "sess-1"}, home=self.home)
        self.assertEqual(got["perm"], "plan")

    def test_the_user_turn_wins_over_a_stale_change_marker(self):
        self.transcript(
            [
                {"type": "permission-mode", "permissionMode": "plan"},
                {"type": "user", "permissionMode": "auto"},
                CLAUDE_ASSISTANT,
            ]
        )
        got = claude.read({"session_id": "sess-1"}, home=self.home)
        self.assertEqual(got["perm"], "auto")

    def test_a_sidechain_user_turn_does_not_set_the_mode(self):
        self.transcript(
            [
                {"type": "user", "permissionMode": "bypassPermissions", "isSidechain": True},
                CLAUDE_ASSISTANT,
            ]
        )
        got = claude.read({"session_id": "sess-1"}, home=self.home)
        self.assertNotIn("perm", got)

    def test_permission_mode_far_behind_the_tail_is_still_found(self):
        # One escalated read covers a mode stamped long before the newest turns.
        filler = json.loads(json.dumps(CLAUDE_ASSISTANT))
        filler["message"]["padding"] = "x" * 40_000
        rows = [{"type": "user", "permissionMode": "plan"}]
        rows.extend(filler for _ in range(10))
        rows.append(CLAUDE_ASSISTANT)
        self.transcript(rows)
        got = claude.read({"session_id": "sess-1"}, home=self.home)
        self.assertEqual(got["perm"], "plan")


CODEX_TURN_CONTEXT = {
    "type": "turn_context",
    "payload": {
        "model": "gpt-5.5",
        "effort": "medium",
        "approval_policy": "on-request",
    },
}
CODEX_TOKEN_COUNT = {
    "type": "event_msg",
    "payload": {
        "type": "token_count",
        "info": {"last_token_usage": {"input_tokens": 16870}},
    },
}


class CodexProviderTests(TempHome):
    def rollout(self, rows, session_id="01a0-abcd"):
        name = "rollout-2026-09-05T23-23-03-%s.jsonl" % session_id
        return write_jsonl(os.path.join(self.home, "sessions", "2026", "09", "05", name), rows)

    def test_reads_model_effort_approval_and_context(self):
        self.rollout([CODEX_TURN_CONTEXT, CODEX_TOKEN_COUNT])
        got = codex.read({"session_id": "01a0-abcd"}, home=self.home)
        self.assertEqual(got["model"], "gpt 5.5")
        self.assertEqual(got["effort"], "medium")
        self.assertEqual(got["perm"], "on-request")
        self.assertEqual(got["ctx"], "17k")

    def test_newest_turn_context_wins(self):
        older = {"type": "turn_context", "payload": {"model": "o3-mini", "effort": "low"}}
        self.rollout([older, CODEX_TURN_CONTEXT])
        got = codex.read({"session_id": "01a0-abcd"}, home=self.home)
        self.assertEqual(got["model"], "gpt 5.5")

    def test_a_rollout_without_usage_still_reports_the_model(self):
        self.rollout([CODEX_TURN_CONTEXT])
        got = codex.read({"session_id": "01a0-abcd"}, home=self.home)
        self.assertEqual(got["model"], "gpt 5.5")
        self.assertNotIn("ctx", got)

    def test_a_stale_session_id_falls_back_to_the_newest_log_for_the_cwd(self):
        turn = {
            "type": "turn_context",
            "payload": {"model": "gpt-5.5", "effort": "high", "cwd": "/home/bal/project/x"},
        }
        self.rollout([turn], session_id="resumed")
        got = codex.read(
            {"session_id": "stale", "cwd": "/home/bal/project/x"}, home=self.home
        )
        self.assertEqual(got["model"], "gpt 5.5")
        self.assertEqual(got["effort"], "high")

    def test_the_fallback_ignores_logs_belonging_to_another_cwd(self):
        turn = {
            "type": "turn_context",
            "payload": {"model": "gpt-5.5", "cwd": "/home/bal/project/other"},
        }
        self.rollout([turn], session_id="other")
        got = codex.read(
            {"session_id": "stale", "cwd": "/home/bal/project/x"}, home=self.home
        )
        self.assertEqual(got, {})

    def test_unknown_session_and_unknown_cwd_yield_nothing_readable(self):
        self.rollout([CODEX_TURN_CONTEXT])
        self.assertEqual(codex.read({"session_id": "ghost"}, home=self.home), {})


class AgyProviderTests(TempHome):
    def settings(self, payload):
        path = os.path.join(self.home, "antigravity-cli", "settings.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def test_effort_is_split_out_of_the_parenthesised_model_name(self):
        self.settings({"model": "Gemini 3.8 Flash (High)"})
        got = agy.read({"session_id": "conv-1"}, home=self.home)
        self.assertEqual(got["model"], "gemini 3.8 flash")
        self.assertEqual(got["effort"], "high")

    def test_a_model_without_a_suffix_reports_no_effort(self):
        self.settings({"model": "Gemini 3.8 Pro"})
        got = agy.read({"session_id": "conv-1"}, home=self.home)
        self.assertEqual(got["model"], "gemini 3.8 pro")
        self.assertNotIn("effort", got)

    def test_missing_settings_yields_nothing_readable(self):
        self.assertEqual(agy.read({"session_id": "conv-1"}, home=self.home), {})

    def test_unreadable_settings_yields_nothing_readable(self):
        path = os.path.join(self.home, "antigravity-cli", "settings.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        self.assertEqual(agy.read({"session_id": "conv-1"}, home=self.home), {})


class RegistryTests(unittest.TestCase):
    def test_supported_agent_kinds_resolve_to_a_provider(self):
        for kind in ("claude", "codex", "agy"):
            self.assertIsNotNone(providers.for_agent(kind))

    def test_agent_kinds_are_matched_case_insensitively(self):
        self.assertIsNotNone(providers.for_agent("Claude"))

    def test_unsupported_agent_kinds_have_no_provider(self):
        self.assertIsNone(providers.for_agent("cursor"))
        self.assertIsNone(providers.for_agent(None))


if __name__ == "__main__":
    unittest.main()
