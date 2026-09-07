"""Rate-limit window formatting."""

import datetime
import unittest

from herdr_model_badge import usage


def at(text):
    """A local wall-clock time as an epoch, so the tests read like the display."""
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


NOW = at("2026-09-07 23:50")


class WindowLabelTests(unittest.TestCase):
    def test_sub_day_windows_are_named_in_hours(self):
        self.assertEqual(usage.window_label(300), "5h")
        self.assertEqual(usage.window_label(60), "1h")

    def test_a_seven_day_window_is_the_week(self):
        self.assertEqual(usage.window_label(10080), "wk")

    def test_longer_windows_are_named_in_days(self):
        self.assertEqual(usage.window_label(43200), "30d")

    def test_an_unknown_window_has_no_label(self):
        self.assertIsNone(usage.window_label(None))
        self.assertIsNone(usage.window_label(0))


class ClassifyTests(unittest.TestCase):
    def test_a_window_within_a_day_is_the_session_window(self):
        self.assertEqual(usage.classify(300), "session")
        self.assertEqual(usage.classify(1440), "session")

    def test_a_longer_window_is_the_period_window(self):
        self.assertEqual(usage.classify(10080), "period")
        self.assertEqual(usage.classify(43200), "period")


class ResetLabelTests(unittest.TestCase):
    def test_a_reset_within_a_day_shows_the_clock_time(self):
        self.assertEqual(usage.reset_label(at("2026-09-08 04:29"), NOW), "→04:29")

    def test_a_reset_further_out_shows_the_date(self):
        self.assertEqual(usage.reset_label(at("2026-09-13 23:59"), NOW), "→09-13")

    def test_a_window_that_already_rolled_over_has_no_label(self):
        # Absolute times never go stale, but a passed reset means the percentage did.
        self.assertIsNone(usage.reset_label(at("2026-09-07 07:29"), NOW))

    def test_an_unknown_reset_has_no_label(self):
        self.assertIsNone(usage.reset_label(None, NOW))


class SegmentTests(unittest.TestCase):
    """A window splits into a percentage and a reset so each can be styled apart."""

    def test_a_full_segment_reads_like_the_statusline(self):
        got = usage.segment(300, 6, at("2026-09-08 04:29"), NOW)
        self.assertEqual(got, ("5h:6%", "→04:29"))

    def test_a_period_segment_shows_a_date(self):
        got = usage.segment(10080, 4, at("2026-09-13 23:59"), NOW)
        self.assertEqual(got, ("wk:4%", "→09-13"))

    def test_a_float_percentage_is_rounded(self):
        self.assertEqual(usage.segment(43200, 0.0, at("2026-10-05 23:23"), NOW),
                         ("30d:0%", "→10-05"))
        self.assertEqual(usage.segment(300, 6.7, at("2026-09-08 04:29"), NOW),
                         ("5h:7%", "→04:29"))

    def test_an_unknown_reset_still_shows_the_percentage(self):
        self.assertEqual(usage.segment(300, 6, None, NOW), ("5h:6%", None))

    def test_a_rolled_over_window_is_dropped_entirely(self):
        self.assertEqual(usage.segment(300, 6, at("2026-09-07 07:29"), NOW), (None, None))

    def test_a_missing_percentage_drops_the_segment(self):
        self.assertEqual(usage.segment(300, None, at("2026-09-08 04:29"), NOW),
                         (None, None))

    def test_an_unknown_window_drops_the_segment(self):
        self.assertEqual(usage.segment(None, 6, at("2026-09-08 04:29"), NOW),
                         (None, None))

    def test_joined_puts_the_reset_back_in_parentheses(self):
        self.assertEqual(usage.joined(("5h:6%", "→04:29")), "5h:6% (→04:29)")
        self.assertEqual(usage.joined(("5h:6%", None)), "5h:6%")
        self.assertIsNone(usage.joined((None, None)))


class CompactTests(unittest.TestCase):
    def test_both_windows_join_into_one_narrow_row(self):
        got = usage.compact(["5h:6%", "wk:4%"])
        self.assertEqual(got, "5h:6%  wk:4%")

    def test_one_window_is_left_as_its_percentage(self):
        self.assertEqual(usage.compact(["30d:0%"]), "30d:0%")

    def test_nothing_readable_is_unknown(self):
        self.assertIsNone(usage.compact([]))
        self.assertIsNone(usage.compact([None, None]))


class WindowsTests(unittest.TestCase):
    """The provider-facing entry point: raw windows in, three tokens out."""

    def test_a_session_and_a_period_window_fill_all_three_tokens(self):
        got = usage.tokens(
            [
                {"minutes": 300, "percent": 6, "resets_at": at("2026-09-08 04:29")},
                {"minutes": 10080, "percent": 4, "resets_at": at("2026-09-13 23:59")},
            ],
            now=NOW,
        )
        self.assertEqual(got["usage_session"], "5h:6% (→04:29)")
        self.assertEqual(got["usage_period"], "wk:4% (→09-13)")
        self.assertEqual(got["usage"], "5h:6%  wk:4%")

    def test_each_window_also_arrives_split_for_separate_styling(self):
        got = usage.tokens(
            [
                {"minutes": 300, "percent": 6, "resets_at": at("2026-09-08 04:29")},
                {"minutes": 10080, "percent": 4, "resets_at": at("2026-09-13 23:59")},
            ],
            now=NOW,
        )
        self.assertEqual(got["usage_session_pct"], "5h:6%")
        self.assertEqual(got["usage_session_at"], "→04:29")
        self.assertEqual(got["usage_period_pct"], "wk:4%")
        self.assertEqual(got["usage_period_at"], "→09-13")

    def test_a_window_with_no_known_reset_yields_no_at_token(self):
        got = usage.tokens([{"minutes": 300, "percent": 6}], now=NOW)
        self.assertEqual(got["usage_session_pct"], "5h:6%")
        self.assertNotIn("usage_session_at", got)

    def test_a_period_only_plan_leaves_the_session_token_out(self):
        got = usage.tokens(
            [{"minutes": 43200, "percent": 0.0, "resets_at": at("2026-10-05 23:23")}],
            now=NOW,
        )
        self.assertNotIn("usage_session", got)
        self.assertEqual(got["usage_period"], "30d:0% (→10-05)")
        self.assertEqual(got["usage"], "30d:0%")

    def test_the_longest_window_wins_its_slot(self):
        # Two period windows: keep the one covering the longer span.
        got = usage.tokens(
            [
                {"minutes": 10080, "percent": 4, "resets_at": at("2026-09-13 23:59")},
                {"minutes": 43200, "percent": 9, "resets_at": at("2026-10-05 23:23")},
            ],
            now=NOW,
        )
        self.assertEqual(got["usage_period"], "30d:9% (→10-05)")

    def test_no_readable_window_yields_no_tokens(self):
        self.assertEqual(usage.tokens([], now=NOW), {})
        self.assertEqual(usage.tokens([{"minutes": 300}], now=NOW), {})


if __name__ == "__main__":
    unittest.main()
