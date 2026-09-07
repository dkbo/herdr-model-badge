"""Session transcripts are append-only and large, so we only ever read their tail."""

import json
import os
import tempfile
import unittest

from herdr_model_badge import tail


class TailLinesTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, text):
        path = os.path.join(self.dir.name, "session.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_lines_come_back_newest_first(self):
        path = self.write("a\nb\nc\n")
        self.assertEqual(list(tail.lines(path)), ["c", "b", "a"])

    def test_missing_trailing_newline_is_fine(self):
        path = self.write("a\nb")
        self.assertEqual(list(tail.lines(path)), ["b", "a"])

    def test_blank_lines_are_skipped(self):
        path = self.write("a\n\n \nb\n")
        self.assertEqual(list(tail.lines(path)), ["b", "a"])

    def test_a_truncated_first_line_is_dropped(self):
        # Reading only the tail can land mid-line; that fragment must not be parsed.
        path = self.write("aaaaaaaaaa\nbbbb\ncc\n")
        self.assertEqual(list(tail.lines(path, max_bytes=8)), ["cc"])

    def test_whole_small_file_is_kept_when_it_fits(self):
        path = self.write("aaaa\nbb\n")
        self.assertEqual(list(tail.lines(path, max_bytes=1024)), ["bb", "aaaa"])

    def test_undecodable_bytes_do_not_raise(self):
        path = os.path.join(self.dir.name, "binary.jsonl")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xfe\n{}\n")
        self.assertEqual(list(tail.lines(path))[0], "{}")

    def test_missing_file_yields_nothing(self):
        self.assertEqual(list(tail.lines(os.path.join(self.dir.name, "nope"))), [])

    def test_empty_file_yields_nothing(self):
        self.assertEqual(list(tail.lines(self.write(""))), [])


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        rows = [
            {"type": "user", "n": 1},
            {"type": "assistant", "n": 2},
            {"type": "user", "n": 3},
            {"type": "assistant", "n": 4},
        ]
        self.path = os.path.join(self.dir.name, "session.jsonl")
        with open(self.path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def test_scan_returns_the_newest_match_for_each_wanted_key(self):
        found = tail.scan(
            self.path,
            {
                "assistant": lambda obj: obj.get("type") == "assistant",
                "user": lambda obj: obj.get("type") == "user",
            },
        )
        self.assertEqual(found["assistant"]["n"], 4)
        self.assertEqual(found["user"]["n"], 3)

    def test_scan_omits_keys_that_never_match(self):
        found = tail.scan(self.path, {"nope": lambda obj: False})
        self.assertEqual(found, {})

    def test_unparsable_lines_are_ignored(self):
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("not json\n")
        found = tail.scan(self.path, {"assistant": lambda obj: obj.get("type") == "assistant"})
        self.assertEqual(found["assistant"]["n"], 4)


if __name__ == "__main__":
    unittest.main()
