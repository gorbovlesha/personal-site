"""Run profile rendering regression checks with Node.js, without dependencies."""

from pathlib import Path
import shutil
import subprocess
import unittest


class ProfessionalTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for rendering checks")
    def test_profile_renders_content_safely(self):
        subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("professional-render.cjs"))],
            check=True,
        )
