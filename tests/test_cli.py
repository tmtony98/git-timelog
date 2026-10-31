"""End-to-end tests: run the real CLI against a throwaway git repo.

Run with: python3 -m unittest discover tests
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "git-timelog"


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "shop-web"
        self.env = {
            **os.environ,
            "GIT_TIMELOG_HOME": str(base / "data"),
            "GIT_TIMELOG_CONFIG": str(base / "config.ini"),
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.commit("init")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def commit(self, msg):
        self.git("commit", "-q", "--allow-empty", "-m", msg)

    def tl(self, *args, check=True):
        r = subprocess.run([sys.executable, str(CLI), *args], cwd=self.repo, env=self.env,
                           capture_output=True, text=True)
        if check and r.returncode:
            self.fail(f"git-timelog {' '.join(args)} failed:\n{r.stderr}")
        return r

    def detail(self, tid):
        code = (
            "import importlib.machinery, importlib.util, json, sys;"
            f"l = importlib.machinery.SourceFileLoader('gtl', {str(CLI)!r});"
            "s = importlib.util.spec_from_loader('gtl', l); m = importlib.util.module_from_spec(s);"
            f"l.exec_module(m); print(json.dumps(m.task_detail(m.db(), {tid})))"
        )
        out = subprocess.run([sys.executable, "-c", code], env=self.env, capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def summary(self):
        code = (
            "import importlib.machinery, importlib.util, json, sys;"
            f"l = importlib.machinery.SourceFileLoader('gtl', {str(CLI)!r});"
            "s = importlib.util.spec_from_loader('gtl', l); m = importlib.util.module_from_spec(s);"
            "l.exec_module(m); print(json.dumps(m.summary(m.db())))"
        )
        out = subprocess.run([sys.executable, "-c", code], env=self.env, capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_hooks_turn_branches_into_tasks(self):
        self.tl("init", "--days", "0")
        self.git("checkout", "-q", "-b", "feat/login")
        self.commit("add login form")
        self.commit("validate login form")
        tasks = {t["branch"]: t for t in self.summary()["tasks"]}
        self.assertIn("feat/login", tasks)
        self.assertEqual(tasks["feat/login"]["commits"], 2)
        self.assertNotIn("main", tasks)

    def test_merge_commit_marks_task_done(self):
        self.tl("init", "--days", "0")
        self.git("checkout", "-q", "-b", "fix/typo")
        self.commit("fix typo")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "fix/typo", "-m", "Merge branch 'fix/typo' into main")
        tasks = {t["branch"]: t for t in self.summary()["tasks"]}
        self.assertEqual(tasks["fix/typo"]["status"], "done")

    def test_returning_to_done_branch_reopens_it(self):
        self.tl("init", "--days", "0")
        self.git("checkout", "-q", "-b", "fix/typo")
        self.commit("fix typo")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "fix/typo", "-m", "Merge branch 'fix/typo' into main")
        time.sleep(1.1)  # events are second-resolution; reopen only when newer than the merge
        self.git("checkout", "-q", "fix/typo")
        tasks = {t["branch"]: t for t in self.summary()["tasks"]}
        self.assertEqual(tasks["fix/typo"]["status"], "doing")

    def test_fast_forward_merge_marks_task_done(self):
        self.tl("init", "--days", "0")
        self.git("checkout", "-q", "-b", "feat/ff")
        self.commit("small change")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--ff-only", "feat/ff")  # no merge commit at all
        tasks = {t["branch"]: t for t in self.summary()["tasks"]}
        self.assertEqual(tasks["feat/ff"]["status"], "done")

    def make_branch(self, name, *msgs):
        self.git("checkout", "-q", "-b", name)
        for i, m in enumerate(msgs):
            (self.repo / f"{name.replace('/', '_')}{i}.txt").write_text(m + "\n")
            self.git("add", "-A")
            self.commit(m)
        self.git("checkout", "-q", "main")

    def status_of(self, branch):
        return next(t for t in self.summary()["tasks"] if t["branch"] == branch)["status"]

    def test_squash_merge_marks_task_done(self):
        self.tl("init", "--days", "0")
        self.make_branch("feat/squashed", "add form", "fix typo", "add validation")
        time.sleep(1.1)  # the squash commit lands after the branch's last commit
        self.git("merge", "-q", "--squash", "feat/squashed")
        self.commit("Add login form (#42)")  # what GitHub's "Squash and merge" leaves behind
        self.assertEqual(self.status_of("feat/squashed"), "done")

    def test_rebase_merge_marks_task_done(self):
        self.tl("init", "--days", "0")
        self.make_branch("feat/rebased", "step one", "step two")
        self.commit("someone else's work on main")  # so the copies below get new ids
        # replay copies onto main, like "Rebase and merge"
        for sha in self.git("rev-list", "--reverse", "main..feat/rebased").split():
            self.git("cherry-pick", sha)
        self.assertEqual(self.status_of("feat/rebased"), "done")

    def test_unmerged_branch_with_similar_name_stays_open(self):
        self.tl("init", "--days", "0")
        self.make_branch("feat/open", "real work")
        self.commit("unrelated change on main")
        self.assertEqual(self.status_of("feat/open"), "doing")

    def test_fresh_branch_is_not_mistaken_for_merged(self):
        self.tl("init", "--days", "0")
        self.git("checkout", "-q", "-b", "feat/new")  # sits inside main, but no commits yet
        tasks = {t["branch"]: t for t in self.summary()["tasks"]}
        self.assertEqual(tasks["feat/new"]["status"], "doing")

    def test_worktrees_share_the_main_repo_name(self):
        self.tl("init", "--days", "0")
        wt = Path(self.tmp.name) / "shop-web-feature"
        self.git("worktree", "add", "-q", "-b", "feat/wt", str(wt))
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "work in worktree"], cwd=wt,
                       env=self.env, check=True)
        tasks = {t["branch"]: t for t in self.summary()["tasks"]}
        self.assertEqual(tasks["feat/wt"]["repo"], "shop-web")
        self.assertEqual(tasks["feat/wt"]["commits"], 1)

    def test_projects_group_repos(self):
        Path(self.env["GIT_TIMELOG_CONFIG"]).write_text("[projects]\nShop = shop-web, shop-api\n")
        self.tl("init", "--days", "0")
        self.git("checkout", "-q", "-b", "feat/cart")
        self.commit("cart")
        s = self.summary()
        shop = next(p for p in s["projects"] if p["name"] == "Shop")
        self.assertEqual(shop["repos"], ["shop-web", "shop-api"])
        self.assertEqual(shop["kpi"]["commits_week"], 1)
        self.assertEqual(next(t for t in s["tasks"] if t["branch"] == "feat/cart")["project"], "Shop")

    def test_dashboard_picks_up_repo_added_while_running(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        srv = subprocess.Popen([sys.executable, "-u", str(CLI), "serve", "--port", str(port)], cwd=self.repo,
                               env=self.env, stdout=subprocess.PIPE, text=True)
        self.addCleanup(srv.kill)
        srv.stdout.readline()  # listening

        def tabs():
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/summary") as r:
                return [p["name"] for p in json.load(r)["projects"]]
        self.assertNotIn("shop-web", tabs())
        self.tl("init", "--days", "0")  # e.g. a new project, while the dashboard is up
        self.assertIn("shop-web", tabs())

    def old_events(self, branch, days_ago):
        """Pretend you last worked on `branch` some days ago (append to the hook log)."""
        ts = int(time.time()) - days_ago * 86400
        log = Path(self.env["GIT_TIMELOG_HOME"]) / "events.log"
        with open(log, "a") as f:
            f.write(f"{ts}\tcommit\tshop-web\t{branch}\tabc1234\twip\n")
            f.write(f"{ts + 60}\tcheckout\tshop-web\tmain\tabc1234\tfrom:{branch}\n")

    def test_idle_unmerged_branch_goes_on_hold_and_resumes(self):
        self.tl("init", "--days", "0")
        self.old_events("feat/paused", 5)
        t = next(t for t in self.summary()["tasks"] if t["branch"] == "feat/paused")
        self.assertEqual((t["status"], t["held_auto"]), ("hold", 1))
        self.git("checkout", "-q", "-b", "feat/paused")  # back on it
        t = next(t for t in self.summary()["tasks"] if t["branch"] == "feat/paused")
        self.assertEqual(t["status"], "doing")

    def test_recent_branch_is_not_held(self):
        self.tl("init", "--days", "0")
        self.old_events("feat/active", 1)
        t = next(t for t in self.summary()["tasks"] if t["branch"] == "feat/active")
        self.assertEqual(t["status"], "doing")

    def test_moving_back_to_doing_resets_the_idle_clock(self):
        self.tl("init", "--days", "0")
        self.old_events("feat/paused", 5)
        self.summary()
        self.tl("status", "feat/paused", "doing")
        t = next(t for t in self.summary()["tasks"] if t["branch"] == "feat/paused")
        self.assertEqual((t["status"], t["held_auto"]), ("doing", 0))

    def test_delete_hides_task_and_time_and_restore_brings_it_back(self):
        self.tl("init", "--days", "0")
        self.tl("add", "Throwaway")
        self.tl("log", "Throwaway", "1h")
        self.tl("delete", "Throwaway")
        s = self.summary()
        self.assertNotIn("Throwaway", [t["title"] for t in s["tasks"]])
        self.assertEqual(s["kpi"]["today"], 0.0)
        self.tl("restore", "Throwaway")
        self.assertIn("Throwaway", [t["title"] for t in self.summary()["tasks"]])

    def test_deleted_branch_task_is_not_recreated_until_you_commit(self):
        self.tl("init", "--days", "0")
        self.git("checkout", "-q", "-b", "feat/lookup")
        self.summary()
        self.tl("delete", "feat/lookup")
        self.git("checkout", "-q", "main")
        self.git("checkout", "-q", "feat/lookup")  # just looking again
        self.assertNotIn("feat/lookup", [t["branch"] for t in self.summary()["tasks"]])
        self.commit("real work")  # working on it again
        self.assertIn("feat/lookup", [t["branch"] for t in self.summary()["tasks"]])

    def agent(self, offset, branch, sid, what, repo="shop-web"):
        """Append a coding-agent event `offset` seconds after a fixed start three hours ago."""
        ts = int(time.time()) - 3 * 3600 + offset
        log = Path(self.env["GIT_TIMELOG_HOME"]) / "events.log"
        with open(log, "a") as f:
            f.write(f"{ts}\tagent\t{repo}\t{branch}\t{sid}\t{what}\n")

    def git_event(self, offset, kind, branch, subject):
        ts = int(time.time()) - 3 * 3600 + offset
        with open(Path(self.env["GIT_TIMELOG_HOME"]) / "events.log", "a") as f:
            f.write(f"{ts}\t{kind}\tshop-web\t{branch}\tabc1234\t{subject}\n")

    def test_research_session_then_branch_is_one_card(self):
        self.tl("init", "--days", "0")
        self.agent(0, "main", "s-A", "prompt|fix the cart badge count")
        self.agent(900, "main", "s-A", "stop")             # agent worked 15 min
        self.agent(1200, "main", "s-A", "prompt")          # you read for 5 min
        self.git_event(1260, "checkout", "fix/cart", "from:main")
        self.agent(2400, "fix/cart", "s-A", "stop")        # agent worked 20 min
        self.git_event(2460, "commit", "fix/cart", "fix cart badge")
        tasks = self.summary()["tasks"]
        self.assertEqual([t["branch"] for t in tasks], ["fix/cart"])  # session card folded in
        self.assertAlmostEqual(tasks[0]["hours"], 2460 / 3600, places=2)  # overlap not double-counted

    def test_research_only_session_gets_its_own_card(self):
        self.tl("init", "--days", "0")
        self.agent(0, "main", "s-B", "prompt|how does auth work")
        self.agent(2400, "main", "s-B", "stop")            # long agent run: counts
        self.agent(4800, "main", "s-B", "prompt")          # 40 min away: doesn't
        self.agent(5100, "main", "s-B", "stop")            # 5 min
        t = next(t for t in self.summary()["tasks"] if t["session"] == "s-B")
        self.assertEqual((t["title"], t["status"]), ("how does auth work", "doing"))
        self.assertAlmostEqual(t["hours"], 2700 / 3600, places=2)
        self.agent(5200, "main", "s-B", "end")
        t = next(t for t in self.summary()["tasks"] if t["session"] == "s-B")
        self.assertEqual(t["status"], "done")

    def test_empty_and_untracked_sessions_make_no_card(self):
        self.tl("init", "--days", "0")
        self.agent(0, "main", "s-C", "start")
        self.agent(60, "main", "s-C", "end")
        self.agent(0, "", "s-D", "prompt|elsewhere", repo="not-tracked")
        self.assertEqual(self.summary()["tasks"], [])

    def test_agent_hook_understands_each_agent(self):
        self.tl("init", "--days", "0")
        hook = ROOT / "hooks" / "agent-hook.sh"
        repo = str(self.repo)
        payloads = {
            "claude": {"hook_event_name": "UserPromptSubmit", "session_id": "c1", "cwd": repo, "prompt": "claude"},
            "codex": {"hook_event_name": "UserPromptSubmit", "session_id": "x1", "cwd": repo, "prompt": "codex",
                      "turn_id": "t1", "model": "m"},
            "gemini": {"hook_event_name": "BeforeAgent", "session_id": "g1", "cwd": repo, "prompt": "gemini"},
            "cursor": {"hook_event_name": "beforeSubmitPrompt", "conversation_id": "k1",
                       "workspace_roots": [repo], "prompt": "cursor"},
        }
        for name, p in payloads.items():
            r = subprocess.run(["bash", str(hook)], input=json.dumps(p), env=self.env,
                               capture_output=True, text=True, check=True)
            self.assertEqual(r.stdout.strip(), '{"continue": true}' if name == "cursor" else "")
        titles = sorted(t["title"] for t in self.summary()["tasks"])
        self.assertEqual(titles, ["claude", "codex", "cursor", "gemini"])

    def run_agent_hook(self, payload):
        r = subprocess.run(["bash", str(ROOT / "hooks" / "agent-hook.sh")], input=json.dumps(payload),
                           env=self.env, capture_output=True, text=True, check=True)
        return r.stdout

    def logged(self):
        log = Path(self.env["GIT_TIMELOG_HOME"]) / "events.log"
        return log.read_text() if log.exists() else ""

    def test_agent_hook_writes_nothing_for_untracked_folders(self):
        self.tl("init", "--days", "0")  # writes the tracked-repos list the hook checks
        other = Path(self.tmp.name) / "private-notes"
        other.mkdir()
        self.run_agent_hook({"hook_event_name": "UserPromptSubmit", "session_id": "p1",
                             "cwd": str(other), "prompt": "something private"})
        self.assertNotIn("private", self.logged())
        self.run_agent_hook({"hook_event_name": "UserPromptSubmit", "session_id": "p2",
                             "cwd": str(self.repo), "prompt": "tracked work"})
        self.assertIn("prompt|tracked work", self.logged())

    def test_detail_offers_resume_commands_for_claude_and_codex(self):
        self.tl("init", "--days", "0")
        repo = str(self.repo)
        for sid, extra in (("c-1111", {"transcript_path": "/home/u/.claude/projects/x/c-1111.jsonl"}),
                           ("x-2222", {"transcript_path": "/home/u/.codex/sessions/x-2222.jsonl", "turn_id": "t"}),
                           ("g-3333", {})):
            ev = "BeforeAgent" if sid.startswith("g") else "UserPromptSubmit"
            self.run_agent_hook({"hook_event_name": ev, "session_id": sid, "cwd": repo, "prompt": sid, **extra})
        by = {}
        for t in self.summary()["tasks"]:
            for s in self.detail(t["id"])["sessions"]:
                by[s["id"]] = s
        self.assertEqual(by["c-1111"]["agent"], "claude")
        self.assertEqual(by["c-1111"]["resume"], f"cd {repo} && claude --resume c-1111")
        self.assertEqual(by["x-2222"]["resume"], f"cd {repo} && codex resume x-2222")
        self.assertEqual((by["g-3333"]["agent"], by["g-3333"]["resume"]), ("gemini", None))

    def open_session(self, sid, dry=False):
        code = (
            "import importlib.machinery, importlib.util, json, sys;"
            f"l = importlib.machinery.SourceFileLoader('gtl', {str(CLI)!r});"
            "s = importlib.util.spec_from_loader('gtl', l); m = importlib.util.module_from_spec(s);"
            f"l.exec_module(m); m.ingest(m.db()); print(json.dumps(m.open_session({sid!r}, dry_run={dry})))"
        )
        out = subprocess.run([sys.executable, "-c", code], env=self.env, capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_open_session_launches_a_terminal_with_the_resume_command(self):
        # a fake "kitty" that records how it was started, instead of opening a window
        fakebin = Path(self.tmp.name) / "bin"
        fakebin.mkdir()
        record = Path(self.tmp.name) / "kitty-args"
        (fakebin / "kitty").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {record}\n')
        (fakebin / "kitty").chmod(0o755)
        self.env["PATH"] = f"{fakebin}:{self.env['PATH']}"
        Path(self.env["GIT_TIMELOG_CONFIG"]).write_text("[git-timelog]\nterminal = kitty\n")
        self.tl("init", "--days", "0")
        self.run_agent_hook({"hook_event_name": "UserPromptSubmit", "session_id": "c-77", "cwd": str(self.repo),
                             "transcript_path": "/h/.claude/projects/p/c-77.jsonl", "prompt": "hi"})
        ok, msg, cmd = self.open_session("c-77")
        self.assertTrue(ok, msg)
        self.assertEqual(cmd, f"cd {self.repo} && claude --resume c-77")
        for _ in range(50):  # the terminal starts in the background
            if record.exists():
                break
            time.sleep(.05)
        self.assertEqual(record.read_text().split("\n")[:3], ["bash", "-ic", f"{cmd}; exec bash"])

    def test_open_session_refuses_what_it_cannot_resume(self):
        self.tl("init", "--days", "0")
        self.run_agent_hook({"hook_event_name": "BeforeAgent", "session_id": "g-1", "cwd": str(self.repo), "prompt": "x"})
        self.assertFalse(self.open_session("g-1")[0])  # Gemini: no resume by id
        self.assertFalse(self.open_session("x; rm -rf ~")[0])  # unknown / unsafe id

    def test_six_column_log_lines_from_older_hooks_still_load(self):
        self.tl("init", "--days", "0")
        self.agent(0, "main", "old-1", "prompt|from an older hook")  # writes the six-column format
        t = next(t for t in self.summary()["tasks"] if t["session"] == "old-1")
        (s,) = self.detail(t["id"])["sessions"]
        self.assertEqual((s["agent"], s["resume"]), (None, None))

    def test_agent_titles_off_keeps_prompt_text_out_of_the_log(self):
        Path(self.env["GIT_TIMELOG_CONFIG"]).write_text("[git-timelog]\nagent_titles = off\n")
        self.tl("init", "--days", "0")
        self.run_agent_hook({"hook_event_name": "UserPromptSubmit", "session_id": "t1",
                             "cwd": str(self.repo), "prompt": "secret plan"})
        self.assertNotIn("secret", self.logged())
        t = next(t for t in self.summary()["tasks"] if t["session"] == "t1")
        self.assertEqual(t["title"], "Agent session")

    def test_agent_hook_cleans_up_long_prompts(self):
        self.tl("init", "--days", "0")
        self.run_agent_hook({"hook_event_name": "UserPromptSubmit", "session_id": "l1", "cwd": str(self.repo),
                             "prompt": "  fix\tthe   cart\n\nbadge " + "x" * 200})
        title = self.logged().strip().split("\t")[5]  # columns: ts kind repo branch session subject agent cwd
        self.assertTrue(title.startswith("prompt|fix the cart badge x"))
        self.assertEqual(len(title), len("prompt|") + 80)

    def agent_cfg(self, agent, content=None):
        """Path of the agent's config inside a throwaway HOME, optionally pre-filled."""
        home = Path(self.tmp.name) / "home"
        self.env["HOME"] = str(home)
        path = home / {"claude": ".claude/settings.json", "codex": ".codex/hooks.json",
                       "gemini": ".gemini/settings.json", "cursor": ".cursor/hooks.json"}[agent]
        path.parent.mkdir(parents=True, exist_ok=True)
        if content is not None:
            path.write_text(content if isinstance(content, str) else json.dumps(content))
        return path

    def test_agent_setup_write_merges_and_keeps_everything_else(self):
        existing = {"model": "opus", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}],
                                               "PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command",
                                                                                             "command": "guard"}]}]}}
        path = self.agent_cfg("claude", existing)
        out = self.tl("agent-setup", "claude", "--write").stdout
        self.assertIn("hooks added", out)
        cfg = json.loads(path.read_text())
        self.assertEqual(cfg["model"], "opus")
        self.assertEqual(cfg["hooks"]["PreToolUse"], existing["hooks"]["PreToolUse"])
        stop_cmds = [h["command"] for e in cfg["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(stop_cmds[0], "notify-send done")
        self.assertTrue(stop_cmds[1].endswith("/git-timelog/hooks/agent-hook.sh") or stop_cmds[1].endswith("hooks/agent-hook.sh"))
        for ev in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"):
            self.assertIn(ev, cfg["hooks"])
        self.assertEqual(json.loads(Path(str(path) + ".git-timelog.bak").read_text()), existing)

    def test_agent_setup_write_twice_changes_nothing_and_remove_restores(self):
        existing = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}]}}
        path = self.agent_cfg("codex", existing)
        self.tl("agent-setup", "codex", "--write")
        once = path.read_text()
        out = self.tl("agent-setup", "codex", "--write").stdout
        self.assertIn("already set up", out)
        self.assertEqual(path.read_text(), once)
        self.assertIn("/hooks", out)  # Codex needs the trust step
        self.tl("agent-setup", "codex", "--remove")
        self.assertEqual(json.loads(path.read_text()), existing)

    def test_agent_setup_write_creates_cursor_config_in_its_format(self):
        path = self.agent_cfg("cursor")
        self.tl("agent-setup", "cursor", "--write")
        cfg = json.loads(path.read_text())
        self.assertEqual(cfg["version"], 1)
        self.assertEqual(sorted(cfg["hooks"]), ["beforeSubmitPrompt", "sessionEnd", "sessionStart", "stop"])
        self.assertIn("command", cfg["hooks"]["stop"][0])
        self.tl("agent-setup", "cursor", "--remove")
        self.assertEqual(json.loads(path.read_text()), {"version": 1})

    def test_agent_setup_refuses_broken_config_or_missing_agent(self):
        path = self.agent_cfg("gemini", "{ not json")
        r = self.tl("agent-setup", "gemini", "--write", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't valid JSON", r.stderr)
        self.assertEqual(path.read_text(), "{ not json")
        path.unlink()
        path.parent.rmdir()
        r = self.tl("agent-setup", "gemini", "--write", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Is gemini installed?", r.stderr)

    def task_id(self, **match):
        return next(t["id"] for t in self.summary()["tasks"] if all(t[k] == v for k, v in match.items()))

    def test_detail_shows_commits_sessions_and_time_by_source(self):
        self.tl("init", "--days", "0")
        self.agent(0, "main", "s-A", "prompt|fix the cart badge")
        self.agent(600, "main", "s-A", "stop")
        self.git_event(700, "checkout", "fix/cart", "from:main")
        self.agent(900, "fix/cart", "s-A", "prompt")
        self.agent(1500, "fix/cart", "s-A", "stop")
        self.git_event(1560, "commit", "fix/cart", "first fix")
        self.git_event(2400, "commit", "fix/cart", "second fix")
        tid = self.task_id(branch="fix/cart")
        d = self.detail(tid)
        self.assertEqual([c["subject"] for c in d["commits"]], ["second fix", "first fix"])  # newest first
        self.assertEqual(d["commits_total"], 2)
        (sess,) = d["sessions"]  # the research session was folded into this card
        self.assertEqual((sess["id"], sess["turns"], sess["title"]), ("s-A", 2, "fix the cart badge"))
        self.assertEqual(sess["seconds"], 1500)
        hours = next(t["hours"] for t in self.summary()["tasks"] if t["id"] == tid)
        self.assertAlmostEqual(d["totals"]["total"] / 3600, hours, places=2)
        for k in ("git", "agent"):
            self.assertLessEqual(d["totals"][k], d["totals"]["total"])
        hidden = next(r for r in self.query("SELECT id FROM tasks WHERE session='s-A'"))
        self.assertIsNone(self.detail(hidden[0]))  # folded session card has no page of its own

    def test_detail_titles_off_deleted_and_manual(self):
        Path(self.env["GIT_TIMELOG_CONFIG"]).write_text("[git-timelog]\nagent_titles = off\n")
        self.tl("init", "--days", "0")
        self.agent(0, "main", "s-R", "prompt|old title written before titles were switched off")
        self.agent(300, "main", "s-R", "stop")
        rid = self.task_id(session="s-R")
        self.assertIsNone(self.detail(rid)["sessions"][0]["title"])
        self.tl("add", "Design review")
        self.tl("log", "Design review", "45m", "figma pass")
        d = self.detail(self.task_id(title="Design review"))
        self.assertEqual((d["commits"], d["sessions"]), ([], []))
        self.assertEqual(d["entries"][0]["note"], "figma pass")
        self.assertEqual(d["totals"]["manual"], 45 * 60)
        self.tl("delete", "Design review")
        tid = next(r[0] for r in self.query("SELECT id FROM tasks WHERE title='Design review'"))
        self.assertIsNone(self.detail(tid))

    def test_detail_caps_long_commit_lists(self):
        self.tl("init", "--days", "0")
        for i in range(60):
            self.git_event(i * 60, "commit", "feat/big", f"step {i}")
        d = self.detail(self.task_id(branch="feat/big"))
        self.assertEqual((len(d["commits"]), d["commits_total"]), (50, 60))
        self.assertEqual(d["commits"][0]["subject"], "step 59")

    def query(self, sql):
        import sqlite3
        self.summary()  # make sure the log is ingested
        return sqlite3.connect(Path(self.env["GIT_TIMELOG_HOME"]) / "timelog.db").execute(sql).fetchall()

    def test_manual_task_and_log(self):
        self.tl("init", "--days", "0")
        self.tl("add", "Sprint planning")
        self.tl("log", "Sprint planning", "1h30m", "notes")
        t = next(t for t in self.summary()["tasks"] if t["title"] == "Sprint planning")
        self.assertAlmostEqual(t["hours"], 1.5, places=2)

    def test_log_defaults_to_current_branch(self):
        self.tl("init", "--days", "0")
        self.git("checkout", "-q", "-b", "feat/search")
        self.tl("log", "45m")
        t = next(t for t in self.summary()["tasks"] if t["branch"] == "feat/search")
        self.assertAlmostEqual(t["hours"], 0.75, places=2)

    def test_bad_duration_is_rejected(self):
        self.tl("add", "x")
        r = self.tl("log", "x", "soon", check=False)
        self.assertNotEqual(r.returncode, 0)

    def test_existing_hook_is_chained_and_remove_restores_it(self):
        hook = self.repo / ".git/hooks/post-commit"
        hook.write_text("#!/bin/sh\necho existing\n")
        hook.chmod(0o755)
        self.tl("init", "--days", "0")
        self.assertIn("echo existing", hook.read_text())
        self.assertIn("# git-timelog", hook.read_text())
        self.tl("remove")
        self.assertEqual(hook.read_text(), "#!/bin/sh\necho existing\n")

    def test_hooks_path_in_work_tree_is_left_alone(self):
        (self.repo / ".husky").mkdir()
        self.git("config", "core.hooksPath", ".husky")
        out = self.tl("init", "--days", "0").stdout
        self.assertIn("add this line", out)
        self.assertEqual(list((self.repo / ".husky").iterdir()), [])

    def test_report_writes_markdown(self):
        self.env["HOME"] = self.tmp.name
        Path(self.env["GIT_TIMELOG_CONFIG"]).write_text(
            f"[git-timelog]\nstandup_dir = {self.tmp.name}/standups\n")
        self.tl("init", "--days", "0")
        self.git("checkout", "-q", "-b", "feat/report")
        self.commit("ship report")
        path = Path(self.tl("report").stdout.strip())
        self.assertIn("ship report", path.read_text())

    def test_demo_fills_empty_database(self):
        self.tl("demo")
        s = self.summary()
        self.assertGreater(len(s["tasks"]), 5)
        self.assertGreater(len(s["activity"]), 10)


if __name__ == "__main__":
    unittest.main()
