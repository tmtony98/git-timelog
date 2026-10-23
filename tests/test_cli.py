"""End-to-end tests: run the real CLI against a throwaway git repo.

Run with: python3 -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
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
