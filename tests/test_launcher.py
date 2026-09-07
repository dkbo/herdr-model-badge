"""The generated statusline launcher."""

import os
import stat
import subprocess
import sys
import tempfile
import unittest

from herdr_model_badge import launcher


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, "state")

    def write(self, root=None):
        return launcher.write(root or os.getcwd(), self.state, "9.9.9")

    def test_the_launcher_lands_on_a_stable_path(self):
        self.assertEqual(self.write(), os.path.join(self.state, "statusline"))

    def test_the_launcher_is_executable(self):
        path = self.write()
        self.assertTrue(os.stat(path).st_mode & stat.S_IXUSR)

    def test_it_pins_the_plugin_root_and_the_state_directory(self):
        with open(self.write(root="/plugins/here"), encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("PYTHONPATH='/plugins/here'", body)
        self.assertIn("HERDR_PLUGIN_STATE_DIR='%s'" % self.state, body)

    def test_a_root_containing_a_space_stays_one_argument(self):
        with open(self.write(root="/plugins/my herdr"), encoding="utf-8") as handle:
            self.assertIn("PYTHONPATH='/plugins/my herdr'", handle.read())

    def test_an_unchanged_launcher_is_not_rewritten(self):
        path = self.write()
        before = os.stat(path).st_mtime_ns
        self.assertEqual(self.write(), path)
        self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_a_moved_plugin_root_rewrites_the_launcher(self):
        self.write(root="/plugins/old")
        with open(self.write(root="/plugins/new"), encoding="utf-8") as handle:
            self.assertIn("PYTHONPATH='/plugins/new'", handle.read())

    def test_an_unwritable_state_directory_is_reported_not_raised(self):
        blocked = os.path.join(self.tmp.name, "blocked")
        with open(blocked, "w", encoding="utf-8") as handle:
            handle.write("x")
        self.assertIsNone(launcher.write(os.getcwd(), os.path.join(blocked, "deeper"), "1"))


class ExecutionTests(unittest.TestCase):
    """The launcher has to actually run, from a directory that is not the plugin."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.path = launcher.write(root, os.path.join(self.tmp.name, "state"), "9.9.9")

    def test_it_passes_the_wrapped_commands_output_through(self):
        completed = subprocess.run(
            [self.path, "printf", "%s", "ctx:6%"],
            input='{"session_id":"s"}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            cwd=self.tmp.name,
            env=dict(os.environ, HERDR_SOCKET_PATH="", HERDR_PANE_ID=""),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "ctx:6%")


if __name__ == "__main__":
    unittest.main()
