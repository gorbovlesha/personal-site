#!/usr/bin/env python3
"""One serialized Trello pipeline step per cron tick. Linux, Python 3.10+."""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local" / "automation"
ROLES = ("developer", "tester", "reviewer")
PROTECTED = ("automation/", ".codex/", ".github/", "AGENTS.md", "tests/test_automation.py")
CHECKS = (("check", "--require-node"), ("test",), ("build", "--require-node"))
GITHUB_APP = "connector_76869538009648d5b282a4bb21c3d157"


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


@contextmanager
def lock_state(state):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "pipeline.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def clean_environment():
    # No GitHub/Trello/API token environment is passed to repository code.
    names = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TERM", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMPDIR")
    return {name: os.environ[name] for name in names if name in os.environ}


class CommandFailed(RuntimeError):
    def __init__(self, executable, returncode):
        super().__init__(f"command_failed:{executable}")
        self.returncode = returncode


def execute(argv, cwd=ROOT, env=None, input_text=None, timeout=180, log=None):
    process = subprocess.Popen([str(a) for a in argv], cwd=cwd, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        output, _ = process.communicate(input_text, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise RuntimeError("process_timeout_or_interruption") from None
    if log:
        log.write_text(output)
        log.chmod(0o600)
    if process.returncode:
        raise CommandFailed(Path(str(argv[0])).name, process.returncode)
    return output.strip()


def sandbox_command(command, directory):
    """Run repository code with no network, host home, credentials or Git metadata."""
    binary = shutil.which("bwrap")
    node = shutil.which("node")
    if not binary or not node:
        raise RuntimeError("test_sandbox_dependencies_missing")
    return [binary, "--die-with-parent", "--unshare-all", "--new-session",
            "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--dir", "/home", "--dir", "/home/agent", "--dir", "/tools",
            "--ro-bind", str(Path(node).resolve()), "/tools/node",
            "--bind", str(Path(directory).resolve()), "/workspace", "--chdir", "/workspace",
            "--setenv", "HOME", "/home/agent", "--setenv", "PATH", "/tools:/usr/bin:/bin",
            "--unsetenv", "CODEX_HOME", "--unsetenv", "XDG_CONFIG_HOME", "--unsetenv", "XDG_DATA_HOME",
            "--", *command]


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
CARD_SCHEMA = object_schema({key: STRING for key in ("id", "url", "name", "description", "list_id", "comments")})
BRIDGE_SCHEMA = object_schema({"ok": {"type": "boolean"}, "error": STRING, "card": CARD_SCHEMA})
RESULT_SCHEMA = object_schema({
    "outcome": {"type": "string", "enum": ["complete", "rework", "blocked"]},
    "summary": STRING, "findings": {"type": "array", "items": STRING},
    "checks": {"type": "array", "items": object_schema({
        "name": STRING, "status": {"type": "string", "enum": ["pass", "fail", "skipped"]}, "evidence": STRING})}})


def validate_schema(value, schema):
    kind = schema["type"]
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "boolean": type(value) is bool}[kind]
    if not valid:
        raise ValueError("invalid_agent_result_type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("invalid_agent_result_enum")
    if kind == "object":
        if set(value) != set(schema["properties"]):
            raise ValueError("invalid_agent_result_fields")
        for key, child in schema["properties"].items():
            validate_schema(value[key], child)
    if kind == "array":
        for item in value:
            validate_schema(item, schema["items"])


class Codex:
    def __init__(self, config, runs):
        self.config, self.runs = config, runs

    def invoke(self, prompt, schema, cwd, bridge=False):
        run = self.runs / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
        run.mkdir(parents=True, mode=0o700)
        atomic_json(run / "schema.json", schema)
        command = [shutil.which("codex") or "codex", "-a", "never", "exec", "--ephemeral",
                   "--sandbox", "read-only" if bridge else "workspace-write", "--color", "never",
                   "-c", "sandbox_workspace_write.network_access=false",
                   "--output-schema", run / "schema.json", "--output-last-message", run / "result.json"]
        if bridge:
            # The Trello adapter never needs GitHub tools, including merge tools.
            command += ["-c", f"apps.{GITHUB_APP}.enabled=false"]
        else:
            command += ["-c", "apps._default.enabled=false"]
        if self.config.get("model"):
            command += ["--model", self.config["model"]]
        command.append("-")
        execute(command, cwd=cwd, env=clean_environment(), input_text=prompt,
                timeout=self.config["bridge_timeout_seconds" if bridge else "role_timeout_seconds"],
                log=run / "agent.log")
        result = read_json(run / "result.json")
        validate_schema(result, schema)
        return result

    def trello(self, operation, **arguments):
        payload = {"operation": operation, "config": self.config, **arguments}
        prompt = (ROOT / "automation/prompts/trello.md").read_text() + "\n\n" + json.dumps(payload, ensure_ascii=False)
        result = self.invoke(prompt, BRIDGE_SCHEMA, ROOT, bridge=True)
        if not result["ok"]:
            raise RuntimeError("trello_operation_blocked")
        return result["card"]

    def worker(self, role, task):
        prompt = (ROOT / "automation/prompts/common.md").read_text()
        prompt += "\n" + (ROOT / f"automation/prompts/{role}.md").read_text()
        prompt += "\n\nContext:\n" + json.dumps(task, ensure_ascii=False)
        result = self.invoke(prompt, RESULT_SCHEMA, Path(task["worktree"]))
        if not result["summary"].strip():
            raise ValueError("empty_agent_summary")
        return result


class GitHub:
    def __init__(self, config):
        self.repo = config["repository"]
        self.base = config["base_branch"]
        self.required = config["required_ci_checks"]

    def api(self, resource, data=None, paginate=False):
        command = [shutil.which("gh") or "gh", "api", f"repos/{self.repo}/{resource}".rstrip("/")]
        if paginate:
            command += ["--paginate", "--slurp"]
        if data is not None:
            command += ["--method", "POST", "--input", "-"]
        return json.loads(execute(command, input_text=json.dumps(data) if data is not None else None))

    def ensure_pr(self, task, summary):
        pulls = self.api(f"pulls?state=all&head={self.repo.split('/')[0]}:{task['branch']}&base={self.base}&per_page=100")
        matches = [p for p in pulls if p["head"]["ref"] == task["branch"]]
        if matches:
            if len(matches) != 1 or matches[0]["state"] != "open":
                raise RuntimeError("pr_closed_or_ambiguous")
            return matches[0]
        return self.api("pulls", {"title": task["name"], "head": task["branch"], "base": self.base,
            "body": f"{summary}\n\nTrello: {task['url']}\n\nMerge выполняет только владелец.", "draft": False})

    def inspect(self, task):
        pr = self.api(f"pulls/{task['pr_number']}")
        if (pr["state"] != "open" or pr.get("merged") or pr.get("auto_merge")
                or pr["head"]["ref"] != task["branch"] or pr["base"]["ref"] != self.base
                or pr["head"]["repo"]["full_name"] != self.repo):
            raise RuntimeError("pr_state_changed")
        return pr

    def ci(self, sha):
        pages = self.api(f"commits/{sha}/check-runs?per_page=100", paginate=True)
        latest = {}
        for page in pages:
            for check in page["check_runs"]:
                name = check["name"]
                if name not in latest or check["id"] > latest[name]["id"]:
                    latest[name] = check
        for name in self.required:
            check = latest.get(name)
            if not check or check["status"] != "completed":
                return "pending"
            if check["conclusion"] != "success":
                return "fail"
        return "pass"

    def comment(self, number, text, marker):
        pages = self.api(f"issues/{number}/comments?per_page=100", paginate=True)
        if any(marker in item["body"] for page in pages for item in page):
            return
        self.api(f"issues/{number}/comments", {"body": text + "\n\n" + marker})


def git(*args, cwd=ROOT):
    return execute(["git", *args], cwd=cwd, env=clean_environment())


def card_key(card_id):
    match = re.fullmatch(r"ari:cloud:trello::card/workspace/[0-9a-f]{24}/([0-9a-f]{24})", card_id)
    if not match:
        raise ValueError("invalid_trello_card_id")
    return match[1]


def changed_paths(worktree):
    tracked = git("diff", "--name-only", "-z", "HEAD", cwd=worktree)
    new = git("ls-files", "--others", "--exclude-standard", "-z", cwd=worktree)
    return [p for p in (tracked + "\0" + new).split("\0") if p]


def assert_allowed_changes(paths):
    if any(path == prefix or path.startswith(prefix) for path in paths for prefix in PROTECTED):
        raise RuntimeError("agent_changed_protected_infrastructure")


def validate_transition(role, result, task):
    validate_schema(result, RESULT_SCHEMA)
    if result["outcome"] == "blocked":
        return "blocked"
    if result["outcome"] == "rework":
        if not result["findings"]:
            raise ValueError("rework_requires_findings")
        return "developer"
    if any(c["status"] == "fail" for c in result["checks"]):
        raise ValueError("complete_with_failed_check")
    if role == "tester" and task.get("visual_change"):
        checks = {item["name"]: item for item in result["checks"]}
        for width in (360, 768, 1440):
            check = checks.get(f"browser-{width}")
            if not check or check["status"] != "pass" or not check["evidence"].strip():
                raise ValueError("browser_evidence_required")
    return {"developer": "tester", "tester": "reviewer", "reviewer": "done"}[role]


class Pipeline:
    def __init__(self, config, state=STATE, agent=None, github=None):
        self.config, self.state = config, state
        self.agent = agent or Codex(config, state / "runs")
        self.github = github or GitHub(config)
        self.path = state / "state.json"
        self.data = read_json(self.path, {"version": 1, "active": None, "pending": None, "halted": None})

    def save(self):
        atomic_json(self.path, self.data)

    def note(self, task, role, summary, suffix):
        marker = f"[site-agent:{card_key(task['id'])}:{role}:{suffix}]"
        self.agent.trello("comment", card_id=task["id"], text=f"[{role}] {summary}", marker=marker)
        if task.get("pr_number"):
            self.github.comment(task["pr_number"], f"[{role}] {summary}", marker)

    def move(self, task, destination, expected):
        card = self.agent.trello("move", card_id=task["id"], destination=self.config["lists"][destination],
                                 expected_lists=[self.config["lists"][key] for key in expected])
        if card["id"] != task["id"] or card["list_id"] != self.config["lists"][destination]:
            raise RuntimeError("unconfirmed_trello_move")

    def check_snapshot(self, task):
        if task.get("pr_number"):
            pr = self.github.inspect(task)
            if pr["head"]["sha"] != task["head_sha"] or pr["base"]["sha"] != task["base_sha"]:
                raise RuntimeError("pr_head_or_base_changed_retest_required")
        elif git("rev-parse", f"origin/{self.config['base_branch']}") != task["head_sha"]:
            raise RuntimeError("base_changed_retest_required")

    def run_checks(self, task):
        for arguments in CHECKS:
            # Exit 100 identifies a completed sandbox whose project command failed.
            wrapper = "import subprocess,sys; sys.exit(100 if subprocess.run(sys.argv[1:]).returncode else 0)"
            command = [sys.executable, "-c", wrapper, sys.executable, "-B", "scripts/project.py", *arguments]
            try:
                execute(sandbox_command(command, task["worktree"]), cwd=task["worktree"],
                        env=clean_environment(), timeout=300,
                        log=self.state / f"last-{arguments[0]}.log")
            except CommandFailed as error:
                if error.returncode == 100:
                    raise RuntimeError("project_checks_failed") from None
                raise RuntimeError("test_sandbox_failed") from None

    def tick(self):
        if self.data["pending"] or self.data["halted"]:
            return "halted"
        task = self.data["active"]
        if not task:
            card = self.agent.trello("select")
            if not card["id"]:
                return "idle"
            key = card_key(card["id"])
            if card["list_id"] != self.config["lists"]["ready"]:
                raise RuntimeError("selected_card_not_ready")
            task = {**card, "branch": f"agents/trello-{key}", "stage": "developer", "attempts": 0,
                    "worktree": str(self.state / "worktrees" / key), "feedback": "", "pr_number": 0}
            self.data["active"] = task
            self.save()
        role = task["stage"]
        self.data["pending"] = {"role": role, "card_id": task["id"], "started_at": now()}
        self.save()  # A crash after this point cannot automatically repeat mutations.
        try:
            card = self.agent.trello("read", card_id=task["id"])
            expected = "in_progress" if role == "developer" else "testing"
            allowed = {self.config["lists"][expected]}
            if role == "developer" and not task["attempts"]:
                allowed.add(self.config["lists"]["ready"])
            if card["id"] != task["id"] or card["list_id"] not in allowed:
                raise RuntimeError("card_was_moved_by_human")
            task.update({key: card[key] for key in ("description", "comments", "name")})
            if role == "developer":
                self.develop(task)
            else:
                self.verify(task, role)
            self.data["pending"] = None
            self.save()
            return self.data["active"]["stage"] if self.data["active"] else "done"
        except (RuntimeError, ValueError, KeyError, OSError) as error:
            # Do not put potentially credential-bearing subprocess output into state.
            self.data["halted"] = {"reason": str(error) if type(error) is RuntimeError else type(error).__name__, "at": now()}
            self.save()
            return "halted"

    def develop(self, task):
        if task["attempts"] >= self.config["max_development_attempts"]:
            raise RuntimeError("development_attempt_limit")
        git("fetch", "origin", self.config["base_branch"])
        base = git("rev-parse", f"origin/{self.config['base_branch']}")
        worktree = Path(task["worktree"])
        if not worktree.exists():
            worktree.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            git("worktree", "add", "-b", task["branch"], str(worktree), base)
        elif task.get("base_sha") and task["base_sha"] != base:
            raise RuntimeError("base_changed_rebase_required")
        self.move(task, "in_progress", ["ready", "in_progress"])
        task["base_sha"] = base
        task["attempts"] += 1
        self.save()
        before = git("rev-parse", "HEAD", cwd=worktree)
        result = self.agent.worker("developer", task)
        if git("rev-parse", "HEAD", cwd=worktree) != before:
            raise RuntimeError("agent_modified_git_head")
        next_stage = validate_transition("developer", result, task)
        if next_stage != "tester":
            self.note(task, "developer", result["summary"], f"attempt-{task['attempts']}")
            raise RuntimeError("developer_blocked_or_incomplete")
        paths = changed_paths(worktree)
        assert_allowed_changes(paths)
        self.run_checks(task)
        paths = changed_paths(worktree)
        assert_allowed_changes(paths)
        if git("rev-parse", "HEAD", cwd=worktree) != before:
            raise RuntimeError("checks_modified_git_head")
        if paths:
            git("add", "--all", cwd=worktree)
            git("-c", "user.name=Personal Site Agent", "-c", "user.email=personal-site-agent@localhost",
                "commit", "-m", f"feat: {task['name']}", cwd=worktree)
        task["head_sha"] = git("rev-parse", "HEAD", cwd=worktree)
        task["visual_change"] = bool(git("diff", "--name-only", base, "HEAD", "--", "src", cwd=worktree))
        if task["head_sha"] != base:
            # Fixed destination: no arbitrary branch, force push, or main update.
            if not re.fullmatch(r"agents/trello-[0-9a-f]{24}", task["branch"]):
                raise RuntimeError("invalid_agent_branch")
            git("push", "origin", f"HEAD:refs/heads/{task['branch']}", cwd=worktree)
            self.save()
            pr = self.github.ensure_pr(task, result["summary"])
            task.update(pr_number=pr["number"], pr_url=pr["html_url"])
        task["developer_result"] = result
        self.save()
        self.note(task, "developer", result["summary"] + ("\nPR: " + task["pr_url"] if task.get("pr_url") else "\nИзменений кода нет; PR не требуется."), task["head_sha"])
        self.move(task, "testing", ["in_progress"])
        task["stage"] = "tester"

    def verify(self, task, role):
        self.check_snapshot(task)
        if task.get("pr_number"):
            ci = self.github.ci(task["head_sha"])
            if ci == "pending":
                return  # Keep stage and retry a read-only CI check on the next tick.
            if ci == "fail":
                self.note(task, role, "CI завершился с ошибкой. Требуется исправление в текущей ветке.", task["head_sha"] + "-ci-failed")
                self.move(task, "in_progress", ["testing"])
                task.update(stage="developer", feedback="Исправить упавший CI", qa=None)
                return
        worktree = Path(task["worktree"])
        if git("rev-parse", "HEAD", cwd=worktree) != task["head_sha"] or changed_paths(worktree):
            raise RuntimeError("worktree_snapshot_mismatch")
        if role == "reviewer":
            qa = task.get("qa")
            if not qa or qa["head_sha"] != task["head_sha"] or qa["base_sha"] != task["base_sha"]:
                raise RuntimeError("qa_not_valid_for_current_snapshot")
        else:
            try:
                self.run_checks(task)
            except RuntimeError as error:
                if str(error) == "project_checks_failed":
                    self.note(task, role, "Обязательные локальные проверки не прошли. Логи сохранены на сервере; требуется исправление.", task["head_sha"] + "-local-failed")
                    self.move(task, "in_progress", ["testing"])
                    task.update(stage="developer", feedback="Обязательные проверки check/test/build не прошли; изучить локальные логи и воспроизвести.", qa=None)
                    return
                raise
        result = self.agent.worker(role, task)
        if changed_paths(worktree) or git("rev-parse", "HEAD", cwd=worktree) != task["head_sha"]:
            raise RuntimeError("verification_agent_changed_code")
        self.check_snapshot(task)
        card = self.agent.trello("read", card_id=task["id"])
        if card["list_id"] != self.config["lists"]["testing"]:
            raise RuntimeError("card_moved_during_verification")
        next_stage = validate_transition(role, result, task)
        self.note(task, role, result["summary"] + ("\n" + "\n".join(result["findings"]) if result["findings"] else ""), task["head_sha"] + f"-attempt-{task['attempts']}")
        if next_stage == "blocked":
            raise RuntimeError(f"{role}_blocked")
        if next_stage == "developer":
            self.move(task, "in_progress", ["testing"])
            task.update(stage="developer", feedback=result["summary"] + "\n" + "\n".join(result["findings"]), qa=None)
        elif next_stage == "reviewer":
            task.update(stage="reviewer", qa={"head_sha": task["head_sha"], "base_sha": task["base_sha"], "result": result})
        else:
            self.check_snapshot(task)
            self.move(task, "done", ["testing"])
            atomic_json(self.state / "completed" / (card_key(task["id"]) + ".json"), {**task, "review": result, "finished_at": now(), "merged_by_agent": False})
            self.data["active"] = None


    def recover(self, stage):
        """Explicit operator recovery after checking remote effects and preserved files."""
        task = self.data["active"]
        if not task or not (self.data["pending"] or self.data["halted"]):
            raise RuntimeError("no_halted_task_to_reconcile")
        card = self.agent.trello("read", card_id=task["id"])
        expected = ["ready", "in_progress"] if stage == "developer" else ["testing"]
        if card["id"] != task["id"] or card["list_id"] not in [self.config["lists"][key] for key in expected]:
            raise RuntimeError("restore_card_to_expected_list_before_recovery")
        if stage != "developer":
            if not task.get("pr_number"):
                raise RuntimeError("no_pr_recovery_requires_manual_reconciliation")
            git("fetch", "origin", self.config["base_branch"], task["branch"])
            pr = self.github.inspect(task)
            head, base = pr["head"]["sha"], pr["base"]["sha"]
            if git("rev-parse", "HEAD", cwd=task["worktree"]) != head or changed_paths(task["worktree"]):
                raise RuntimeError("restore_clean_worktree_to_pr_head_before_recovery")
            git("merge-base", "--is-ancestor", base, head, cwd=task["worktree"])
            if stage == "reviewer" and (not task.get("qa") or task["qa"]["head_sha"] != head or task["qa"]["base_sha"] != base):
                raise RuntimeError("repeat_tester_before_reviewer")
            task.update(head_sha=head, base_sha=base)
        if stage == "tester":
            task["qa"] = None
        task["stage"] = stage
        self.data.update(pending=None, halted=None, last_recovery={"at": now(), "stage": stage, "card_id": task["id"]})
        self.save()


def preflight(config, online=False, state=STATE):
    problems = []
    for executable in ("git", "codex", "gh", "node", "bwrap"):
        if not shutil.which(executable):
            problems.append(f"missing_executable:{executable}")
    try:
        git("rev-parse", "HEAD")
    except RuntimeError:
        problems.append("initial_commit_missing")
    expected = {f"https://github.com/{config['repository']}.git", f"git@github.com:{config['repository']}.git"}
    try:
        if git("remote", "get-url", "origin") not in expected:
            problems.append("origin_does_not_match_config")
    except RuntimeError:
        problems.append("origin_missing")
    try:
        execute([shutil.which("gh") or "gh", "auth", "status", "--hostname", "github.com"])
    except (RuntimeError, OSError):
        problems.append("github_cli_not_authenticated")
    if online and not problems:
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix="sandbox-probe-", dir=state) as directory:
            execute(sandbox_command([sys.executable, "-c", "print('sandbox-ready')"], directory), env=clean_environment())
        git("fetch", "origin", config["base_branch"])
        repository = GitHub(config).api("")
        if repository["full_name"] != config["repository"] or not repository.get("permissions", {}).get("push"):
            problems.append("github_write_access_missing")
        Codex(config, state / "runs").trello("probe")
    return problems


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "tick", "status", "enable", "pause", "recover"))
    parser.add_argument("--online", action="store_true", help="Verify GitHub, Git transport, and actual cron-user Trello access")
    parser.add_argument("--stage", choices=ROLES)
    parser.add_argument("--confirm-reconciled", action="store_true")
    args = parser.parse_args()
    config = read_json(ROOT / "automation/config.json")
    if args.command == "pause":
        (STATE / "enabled").unlink(missing_ok=True)
        print('{"status":"paused"}')
        return 0
    with lock_state(STATE) as acquired:
        if not acquired:
            print('{"status":"busy"}')
            return 0
        pipeline = Pipeline(config)
        if args.command == "status":
            print(json.dumps({"enabled": (STATE / "enabled").exists(), **pipeline.data}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "recover":
            if not args.stage or not args.confirm_reconciled:
                parser.error("recover requires --stage and --confirm-reconciled after manual reconciliation")
            try:
                pipeline.recover(args.stage)
            except (RuntimeError, ValueError, OSError, KeyError) as error:
                print(json.dumps({"status": "blocked", "reason": str(error) if type(error) is RuntimeError else type(error).__name__}))
                return 1
            print('{"status":"reconciled"}')
            return 0
        if args.command == "pause":
            (STATE / "enabled").unlink(missing_ok=True)
            print('{"status":"paused"}')
            return 0
        if args.command in ("doctor", "enable"):
            try:
                problems = preflight(config, online=args.online or args.command == "enable")
            except (RuntimeError, ValueError, OSError, KeyError):
                problems = ["online_preflight_failed_see_private_logs"]
            print(json.dumps({"status": "blocked" if problems else "ready", "problems": problems}, ensure_ascii=False))
            if problems:
                return 1
            if args.command == "enable":
                if pipeline.data["pending"] or pipeline.data["halted"]:
                    print('{"status":"halted_reconciliation_required"}')
                    return 1
                (STATE / "enabled").touch(mode=0o600)
            return 0
        if not (STATE / "enabled").exists():
            print('{"status":"disabled"}')
            return 0
        if pipeline.data["pending"] or pipeline.data["halted"]:
            print('{"status":"halted_reconciliation_required"}')
            return 1
        problems = preflight(config)
        if problems:
            print(json.dumps({"status": "blocked", "problems": problems}))
            return 1
        print(json.dumps({"status": pipeline.tick()}), flush=True)
        return 1 if pipeline.data["halted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
