"""End-to-end tests: run the real CLI against a throwaway git repo.

Run with: python3 -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import tempfile
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
