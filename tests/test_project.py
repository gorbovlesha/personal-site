"""Regression checks for publishing boundaries and build behavior."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("project", Path(__file__).resolve().parents[1] / "scripts" / "project.py")
project = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "src"
        self.source.mkdir()
        self.write("index.html", '<main id="main"><a href="#main">Home</a></main>')

    def write(self, name, content):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_accepts_nested_assets_and_cross_page_fragments(self):
        self.write("index.html", '<a href="notes/index.html#note">Note</a><link href="styles.css?v=1" rel="stylesheet">')
        self.write("notes/index.html", '<h1 id="note">Note</h1><a href="../index.html">Home</a>')
        self.write("styles.css", "body { color: black; }")
        self.assertEqual(project.validate_source(self.source), 3)

    def test_rejects_broken_asset_and_fragment(self):
        for html in ('<script src="missing.js"></script>', '<a href="#missing">Oops</a>'):
            with self.subTest(html=html):
                self.write("index.html", html)
                with self.assertRaises(ValueError):
                    project.validate_source(self.source)

    def test_rejects_duplicate_ids(self):
        self.write("index.html", '<p id="same"></p><p id="same"></p>')
        with self.assertRaisesRegex(ValueError, "Duplicate IDs"):
            project.validate_source(self.source)

    def test_rejects_files_outside_source(self):
        (self.root / "secret.txt").write_text("private")
        self.write("index.html", '<a href="%2e%2e/secret.txt">Bad</a>')
        with self.assertRaisesRegex(ValueError, "escapes src"):
            project.validate_source(self.source)

    def test_rejects_hidden_files(self):
        self.write(".env", "SECRET=not-for-the-web")
        with self.assertRaisesRegex(ValueError, "Hidden files"):
            project.validate_source(self.source)

    def test_rejects_symlinks_in_source(self):
        (self.source / "linked").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            project.validate_source(self.source)

    @patch.object(project, "check_javascript")
    def test_build_copies_assets_and_removes_stale_output(self, _check):
        self.write("assets/icon.svg", '<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        output = self.root / "dist"
        output.mkdir()
        (output / "stale.txt").write_text("old")
        project.build(self.root)
        self.assertFalse((output / "stale.txt").exists())
        self.assertEqual((output / "index.html").read_bytes(), (self.source / "index.html").read_bytes())
        self.assertTrue((output / "assets/icon.svg").is_file())

    @patch.object(project, "check_javascript")
    def test_failed_validation_preserves_previous_build(self, _check):
        output = self.root / "dist"
        output.mkdir()
        (output / "previous.txt").write_text("keep")
        self.write("index.html", '<img src="missing.png">')
        with self.assertRaises(ValueError):
            project.build(self.root)
        self.assertEqual((output / "previous.txt").read_text(), "keep")

    @patch.object(project, "check_javascript")
    def test_build_refuses_symlinked_output(self, _check):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "keep.txt").write_text("keep")
        (self.root / "dist").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Refusing to replace"):
            project.build(self.root)
        self.assertEqual((elsewhere / "keep.txt").read_text(), "keep")

    @patch.object(project.shutil, "which", return_value=None)
    def test_ci_cannot_silently_skip_javascript(self, _which):
        with self.assertRaisesRegex(ValueError, "Node.js is required"):
            project.check_javascript(self.root, require_node=True)


if __name__ == "__main__":
    unittest.main()
