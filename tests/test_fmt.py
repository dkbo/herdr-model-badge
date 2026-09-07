"""Display formatting is the part users see, so it gets the most explicit tests."""

import unittest

from herdr_model_badge import fmt


class ClaudeModelTests(unittest.TestCase):
    def test_current_families(self):
        self.assertEqual(fmt.claude_model("claude-opus-5"), "opus 5")
        self.assertEqual(fmt.claude_model("claude-sonnet-5"), "sonnet 5")
        self.assertEqual(fmt.claude_model("claude-fable-5-1"), "fable 5.1")

    def test_dated_snapshot_id_drops_the_date(self):
        self.assertEqual(fmt.claude_model("claude-haiku-4-5-20251001"), "haiku 4.5")

    def test_context_variant_suffix_is_dropped(self):
        # The transcript never records "[1m]", but an id may still arrive with it.
        self.assertEqual(fmt.claude_model("claude-opus-5[1m]"), "opus 5")

    def test_legacy_family_last_ordering(self):
        self.assertEqual(fmt.claude_model("claude-3-7-sonnet-20250219"), "sonnet 3.7")
        self.assertEqual(fmt.claude_model("claude-3-5-haiku-20241022"), "haiku 3.5")

    def test_bedrock_and_vertex_style_ids(self):
        self.assertEqual(fmt.claude_model("us.anthropic.claude-opus-5-v1:0"), "opus 5")

    def test_unknown_family_falls_back_to_spaced_words(self):
        self.assertEqual(fmt.claude_model("claude-newthing-9"), "newthing 9")

    def test_blank_input_is_unknown(self):
        self.assertIsNone(fmt.claude_model(""))
        self.assertIsNone(fmt.claude_model(None))


class GenericModelTests(unittest.TestCase):
    def test_codex_ids(self):
        self.assertEqual(fmt.generic_model("gpt-5.5"), "gpt 5.5")
        self.assertEqual(fmt.generic_model("gpt-5-codex"), "gpt 5 codex")
        self.assertEqual(fmt.generic_model("o3-mini"), "o3 mini")

    def test_already_spaced_names_are_kept(self):
        self.assertEqual(fmt.generic_model("Gemini 3.8 Flash"), "gemini 3.8 flash")

    def test_blank_input_is_unknown(self):
        self.assertIsNone(fmt.generic_model("   "))


class EffortTests(unittest.TestCase):
    def test_known_levels_are_lowercased(self):
        self.assertEqual(fmt.effort("High"), "high")
        self.assertEqual(fmt.effort("medium"), "medium")
        self.assertEqual(fmt.effort("MINIMAL"), "minimal")

    def test_blank_input_is_unknown(self):
        self.assertIsNone(fmt.effort(None))
        self.assertIsNone(fmt.effort(""))


class TokenCountTests(unittest.TestCase):
    def test_small_counts_are_exact(self):
        self.assertEqual(fmt.token_count(0), "0")
        self.assertEqual(fmt.token_count(999), "999")

    def test_thousands_are_rounded(self):
        self.assertEqual(fmt.token_count(1000), "1k")
        self.assertEqual(fmt.token_count(104272), "104k")

    def test_millions_get_one_decimal(self):
        self.assertEqual(fmt.token_count(1_040_000), "1.0M")
        self.assertEqual(fmt.token_count(1_250_000), "1.2M")

    def test_non_numbers_are_unknown(self):
        self.assertIsNone(fmt.token_count(None))
        self.assertIsNone(fmt.token_count("lots"))
        self.assertIsNone(fmt.token_count(-1))


class BadgeTests(unittest.TestCase):
    def test_model_and_effort_are_joined_with_a_middle_dot(self):
        self.assertEqual(fmt.badge("opus 5", "high"), "opus 5 · high")

    def test_model_alone_needs_no_separator(self):
        self.assertEqual(fmt.badge("sonnet 5", None), "sonnet 5")

    def test_effort_alone_still_reads(self):
        self.assertEqual(fmt.badge(None, "high"), "high")

    def test_nothing_readable_is_unknown(self):
        self.assertIsNone(fmt.badge(None, None))


if __name__ == "__main__":
    unittest.main()
