#!/usr/bin/env python3
"""Dependency-free development commands for the static personal site."""

import argparse
from collections import Counter
from functools import partial
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class PageReferences(HTMLParser):
    """Collect IDs and locally referenced files without executing page scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = []
        self.references = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag in ("script", "img", "source") and attrs.get("src"):
            self.references.append(attrs["src"])
        if tag in ("a", "link") and attrs.get("href"):
            self.references.append(attrs["href"])


def validate_source(source):
    """Fail on missing assets, duplicate IDs, unsafe paths, or broken anchors."""
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("src must be a real directory")
    source = source.resolve()
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not allowed in src: {path.name}")
        if any(part.startswith(".") for part in path.relative_to(source).parts):
            raise ValueError(f"Hidden files are not publishable: {path.name}")
    if not (source / "index.html").is_file():
        raise ValueError("src/index.html is missing")

    pages = {}
    for path in source.rglob("*.html"):
        page = PageReferences()
        page.feed(path.read_text(encoding="utf-8"))
        duplicate_ids = [name for name, count in Counter(page.ids).items() if count > 1]
        if duplicate_ids:
            raise ValueError(f"Duplicate IDs in {path.name}: {duplicate_ids}")
        pages[path.resolve()] = page

    for path, page in pages.items():
        for reference in page.references:
            url = urlsplit(reference)
            if url.scheme or url.netloc:
                continue
            relative = unquote(url.path)
            if relative.startswith("/"):
                target = source / relative.lstrip("/")
            else:
                target = path.parent / relative if relative else path
            target = target.resolve()
            if not target.is_relative_to(source):
                raise ValueError(f"Reference escapes src: {reference}")
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                raise ValueError(f"Missing local asset in {path.name}: {reference}")
            if url.fragment and target in pages:
                if unquote(url.fragment) not in pages[target].ids:
                    raise ValueError(f"Missing anchor in {path.name}: {reference}")
    return sum(1 for path in source.rglob("*") if path.is_file())


def check_javascript(root, require_node=False):
    node = shutil.which("node")
    if not node:
        if require_node:
            raise ValueError("Node.js is required for JavaScript checks")
        print("SKIP: JavaScript checks (Node.js not installed)", flush=True)
        return
    for path in sorted((root / "src").rglob("*.js")):
        subprocess.run([node, "--check", str(path)], check=True)
    subprocess.run([node, str(root / "scripts" / "check-content.cjs")], check=True)
    print("OK: JavaScript syntax and content contract", flush=True)


def build(root=ROOT, require_node=False):
    root = Path(root).resolve()
    source = root / "src"
    output = root / "dist"
    count = validate_source(source)
    check_javascript(root, require_node)
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ValueError("Refusing to replace dist: expected a real directory")
    # Only the fixed, generated directory under the project root is removed.
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source, output)
    print(f"Built {count} files into {output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "build"):
        sub = commands.add_parser(command)
        sub.add_argument("--require-node", action="store_true")
    commands.add_parser("test")
    for command in ("dev", "preview"):
        sub = commands.add_parser(command)
        sub.add_argument("--port", type=int, default=8080)
        sub.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    try:
        if args.command == "check":
            print(f"OK: {validate_source(ROOT / 'src')} source files and local references", flush=True)
            check_javascript(ROOT, args.require_node)
        elif args.command == "build":
            build(require_node=args.require_node)
        elif args.command == "test":
            subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"], cwd=ROOT, check=True)
        else:
            directory = ROOT / ("src" if args.command == "dev" else "dist")
            if not (directory / "index.html").is_file():
                raise ValueError("Site is missing; run build before preview")
            handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
            with ThreadingHTTPServer((args.host, args.port), handler) as server:
                print(f"Serving {directory.name}: http://{args.host}:{server.server_port} (Ctrl+C to stop)", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
