#!/usr/bin/env python3
"""Install only this user's marked cron block, after successful live preflight."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "# BEGIN personal-site-agents"
END = "# END personal-site-agents"


def replace_block(existing, replacement):
    lines = existing.splitlines()
    if sum(line == BEGIN for line in lines) != sum(line == END for line in lines):
        raise ValueError("Malformed existing cron block; inspect it manually")
    kept, inside = [], False
    for line in lines:
        if line == BEGIN:
            if inside:
                raise ValueError("Nested cron block")
            inside = True
        elif line == END:
            if not inside:
                raise ValueError("Unmatched cron marker")
            inside = False
        elif not inside:
            kept.append(line)
    text = "\n".join(kept).rstrip()
    return (text + "\n" if text else "") + replacement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if any(char in str(ROOT) for char in " %\n"):
        raise SystemExit("Cron installation requires a path without spaces, percent signs or newlines")
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if existing.returncode and "no crontab for" not in existing.stderr.lower():
        raise SystemExit("Cannot safely read current crontab; existing jobs were not changed")
    block = ""
    if args.remove:
        subprocess.run([sys.executable, str(ROOT / "automation/runner.py"), "pause"], check=True)
    else:
        # Does not take cards or change external data. Fails closed if actual access is missing.
        subprocess.run([sys.executable, str(ROOT / "automation/runner.py"), "enable"], check=True)
        user_path = str(Path.home() / ".local/bin") + ":/usr/local/bin:/usr/bin:/bin"
        block = (BEGIN + "\n" + "*/5 * * * * PATH=" + user_path + " " + sys.executable + " " +
                 str(ROOT / "automation/runner.py") + " tick >> " +
                 str(ROOT / ".local/automation/cron.log") + " 2>&1\n" + END + "\n")
    subprocess.run(["crontab", "-"], input=replace_block(existing.stdout, block), text=True, check=True)
    print("Cron removed" if args.remove else "Cron installed: every 5 minutes, one step per tick")


if __name__ == "__main__":
    main()
