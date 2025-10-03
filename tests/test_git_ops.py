from __future__ import annotations

import types

import pytest

from git_branch_list import git_ops


def test_which(monkeypatch):
    monkeypatch.setattr(git_ops.shutil, "which", lambda c: True)
    assert git_ops.which("fzf") is True
    monkeypatch.setattr(git_ops.shutil, "which", lambda c: None)
    assert git_ops.which("fzf") is False


def test_ensure_git_repo_required_false(monkeypatch):
    class E(Exception):
        pass

    def _run_fail(cmd, check=True, cwd=None):  # noqa: ANN001, ARG001
        raise git_ops.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(git_ops, "run", _run_fail)
    assert git_ops.ensure_git_repo(required=False) is False


def test_ensure_deps_interactive(monkeypatch):
    # when fzf missing -> sys.exit(1)
    monkeypatch.setattr(git_ops, "which", lambda c: False)
    with pytest.raises(SystemExit):
        git_ops.ensure_deps(interactive=True)
    # when fzf present -> ensure_git_repo called
    called = {"repo": False}
    monkeypatch.setattr(git_ops, "which", lambda c: True)
    monkeypatch.setattr(
        git_ops, "ensure_git_repo", lambda required=True: called.__setitem__("repo", True)
    )
    git_ops.ensure_deps(interactive=True)
    assert called["repo"] is True


def test_term_cols(monkeypatch):
    # Test normal case
    monkeypatch.setattr(
        git_ops.shutil, "get_terminal_size", lambda: types.SimpleNamespace(columns=123)
    )
    assert git_ops.term_cols() == 123

    # Test fallback on exception - clean up the mock first
    monkeypatch.undo()

    # Create a targeted mock just for this function
    original_term_cols = git_ops.term_cols

    def mock_term_cols(default=120):
        try:
            # This will fail
            raise OSError
        except Exception:
            return default

    monkeypatch.setattr(git_ops, "term_cols", mock_term_cols)
    assert git_ops.term_cols(default=77) == 77

    # Restore original
    monkeypatch.setattr(git_ops, "term_cols", original_term_cols)


def test_get_current_branch(monkeypatch):
    monkeypatch.setattr(
        git_ops, "run", lambda cmd, check=True: types.SimpleNamespace(stdout="main\n")
    )
    assert git_ops.get_current_branch() == "main"

    def _fail(cmd, check=True):  # noqa: ANN001, ARG001
        raise git_ops.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(git_ops, "run", _fail)
    assert git_ops.get_current_branch() == ""


def test_iter_local_branches_parsing(monkeypatch):
    out = "* main\n  feature/x\n(HEAD detached at abc)\n(no branch)\n+ other\n"
    monkeypatch.setattr(git_ops, "run", lambda cmd, check=True: types.SimpleNamespace(stdout=out))
    brs = list(git_ops.iter_local_branches(limit=None))
    assert brs == ["main", "feature/x", "other"]
    assert list(git_ops.iter_local_branches(limit=2)) == ["main", "feature/x"]


def test_iter_remote_branches_parsing(monkeypatch):
    out = "origin/HEAD -> origin/main\norigin/main\nupstream/dev\norigin/feature\norigin/HEAD\n"
    monkeypatch.setattr(git_ops, "run", lambda cmd, check=True: types.SimpleNamespace(stdout=out))
    brs = list(git_ops.iter_remote_branches("origin", limit=None))
    assert brs == ["main", "feature"]
    assert list(git_ops.iter_remote_branches("origin", limit=1)) == ["main"]


def test_build_and_get_last_commit_cache(monkeypatch):
    # two valid lines and one malformed
    fmt_out = (
        "branch1\x00aaaaaaaa\x001234567\x001700000000\x00feat: subject 1\n"
        "branch2\x00bbbbbbbb\x00abc1234\x001600000000\x00fix: subject 2\n"
        "oops\n"
    )
    monkeypatch.setattr(
        git_ops,
        "run",
        lambda cmd, check=True: types.SimpleNamespace(stdout=fmt_out),
    )
    mapping = git_ops.build_last_commit_cache_for_refs(["refs/heads/*"])
    assert mapping["branch1"][1] == "aaaaaaaa"
    assert mapping["branch2"][2] == "abc1234"
    # cached access
    assert git_ops.get_last_commit_from_cache("branch1")[3] == "feat: subject 1"


def test_remote_ssh_url_and_dirty(monkeypatch):
    # https -> ssh
    monkeypatch.setattr(
        git_ops,
        "run",
        lambda cmd: types.SimpleNamespace(stdout="https://github.com/owner/repo.git\n"),
    )
    assert git_ops.remote_ssh_url("origin") == "git@github.com:owner/repo.git"

    # run failure returns remote
    def _fail(cmd):  # noqa: ANN001
        raise git_ops.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(git_ops, "run", _fail)
    assert git_ops.remote_ssh_url("origin") == "origin"

    # dirty detection
    monkeypatch.setattr(
        git_ops, "run", lambda cmd, check=True: types.SimpleNamespace(stdout=" M a\n")
    )
    assert git_ops.is_workdir_dirty() is True
    monkeypatch.setattr(git_ops, "run", lambda cmd, check=True: types.SimpleNamespace(stdout="\n"))
    assert git_ops.is_workdir_dirty() is False

    def _err(cmd, check=True):  # noqa: ANN001, ARG001
        raise RuntimeError

    monkeypatch.setattr(git_ops, "run", _err)
    assert git_ops.is_workdir_dirty() is False


def test_is_branch_in_worktree(monkeypatch):
    # Branch is in worktree
    worktree_output = "worktree /path/to/worktree\nbranch refs/heads/feature\nworktree /path/to/main\nbranch refs/heads/main\n"
    monkeypatch.setattr(
        git_ops, "run", lambda cmd, check=True: types.SimpleNamespace(stdout=worktree_output)
    )
    assert git_ops.is_branch_in_worktree("feature") == "/path/to/worktree"
    assert git_ops.is_branch_in_worktree("main") == "/path/to/main"
    assert git_ops.is_branch_in_worktree("nonexistent") == ""

    # Error case
    def _fail(cmd, check=True):  # noqa: ANN001, ARG001
        raise git_ops.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(git_ops, "run", _fail)
    assert git_ops.is_branch_in_worktree("feature") == ""


def test_get_worktree_path(monkeypatch):
    # Branch is in worktree
    worktree_output = "worktree /path/to/feature-worktree\nbranch refs/heads/feature\nworktree /path/to/main\nbranch refs/heads/main\n"
    monkeypatch.setattr(
        git_ops, "run", lambda cmd, check=True: types.SimpleNamespace(stdout=worktree_output)
    )
    assert git_ops.get_worktree_path("feature") == "/path/to/feature-worktree"
    assert git_ops.get_worktree_path("main") == "/path/to/main"
    assert git_ops.get_worktree_path("nonexistent") is None

    # Error case
    def _fail(cmd, check=True):  # noqa: ANN001, ARG001
        raise git_ops.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(git_ops, "run", _fail)
    assert git_ops.get_worktree_path("feature") is None
