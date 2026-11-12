"""Run navigation behavior checks using the project's existing Node.js runtime."""

from pathlib import Path
import shutil
import subprocess
import unittest


class NavigationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for navigation behavior tests")
    def test_navigation_behavior(self):
        subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("navigation.cjs"))],
            check=True,
        )
