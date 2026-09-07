"""Fallback session-log discovery."""

import os
import tempfile
import time
import unittest

from herdr_model_badge import discover


class NewestFirstTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def touch(self, name, mtime):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x")
        os.utime(path, (mtime, mtime))
        return path

    def test_paths_come_back_newest_first(self):
        now = time.time()
        old = self.touch("old.jsonl", now - 100)
        new = self.touch("new.jsonl", now)
        pattern = os.path.join(self.tmp.name, "*.jsonl")
        self.assertEqual(discover.newest_first(pattern), [new, old])

    def test_the_candidate_list_is_capped(self):
        now = time.time()
        for index in range(5):
            self.touch("s%d.jsonl" % index, now - index)
        pattern = os.path.join(self.tmp.name, "*.jsonl")
        self.assertEqual(len(discover.newest_first(pattern, limit=2)), 2)

    def test_no_matches_is_an_empty_list(self):
        self.assertEqual(discover.newest_first(os.path.join(self.tmp.name, "*.none")), [])


class FirstNamingCwdTests(unittest.TestCase):
    def test_the_first_log_claiming_the_cwd_wins(self):
        recorded = {"a": "/other", "b": "/wanted", "c": "/wanted"}
        got = discover.first_naming_cwd(["a", "b", "c"], "/wanted", recorded.get)
        self.assertEqual(got, "b")

    def test_trailing_separators_still_match(self):
        got = discover.first_naming_cwd(["a"], "/wanted/", lambda path: "/wanted")
        self.assertEqual(got, "a")

    def test_no_claim_means_no_match(self):
        self.assertIsNone(discover.first_naming_cwd(["a"], "/wanted", lambda path: None))

    def test_an_unknown_cwd_never_matches(self):
        self.assertIsNone(discover.first_naming_cwd(["a"], None, lambda path: "/wanted"))

    def test_an_unreadable_candidate_is_skipped(self):
        def cwd_of(path):
            if path == "a":
                raise OSError("gone")
            return "/wanted"

        self.assertEqual(discover.first_naming_cwd(["a", "b"], "/wanted", cwd_of), "b")


if __name__ == "__main__":
    unittest.main()
