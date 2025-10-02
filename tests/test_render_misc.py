from __future__ import annotations

import types

from git_branch_list import render


def test_get_git_color_and_setup_colors(monkeypatch):
    monkeypatch.setattr(render, "run", lambda cmd: types.SimpleNamespace(stdout="\x1b[31m\n"))
    assert render.get_git_color("color.branch.local", "normal") == "\x1b[31m"
    c = render.setup_colors(no_color=False)
    assert isinstance(c, render.Colors)
    c2 = render.setup_colors(no_color=True)
    assert c2.reset == ""


def test_format_branch_info_with_cache_and_links(monkeypatch):
    # Provide cache hit
    monkeypatch.setattr(
        render,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "feat: hello"),
    )
    # Make github detection return base to enable OSC8 link path
    monkeypatch.setattr(render, "_detect_github_owner_repo", lambda: ("o", "r"))
    colors = render.Colors(commit="C", date="D", local="L", current="X", reset="R")
    out = render.format_branch_info("branch-name", "branch-name", False, colors, max_width=120)
    assert "branch-name" in out
    assert "deadbee" in out
    # OSC8 link esc sequence present
    assert "\x1b]8;;https://github.com/o/r/commit/" in out


def test_git_log_oneline_with_and_without_colors(monkeypatch):
    # No colors: passthrough
    monkeypatch.setattr(render, "run", lambda cmd, **kwargs: types.SimpleNamespace(stdout="x\n"))
    assert render.git_log_oneline("ref", colors=None) == "x\n"

    # With colors and link building
    def _run(cmd, *a, **k):  # noqa: ANN001, D401
        return types.SimpleNamespace(stdout="aaaaaaaa aaaaaaa feat: subject\ninvalid line\n")

    monkeypatch.setattr(render, "run", _run)
    monkeypatch.setattr(render, "_detect_github_owner_repo", lambda: ("o", "r"))
    cols = render.Colors(commit="C", reset="R", feat="F")
    out = render.git_log_oneline("ref", n=1, colors=cols)
    assert "subject" in out and "https://github.com/o/r/commit/aaaaaaaa" in out


def test_format_branch_info_with_pr_info(monkeypatch):
    # Mock cache and github detection
    monkeypatch.setattr(
        render,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "feat: original subject"),
    )
    monkeypatch.setattr(render, "_detect_github_owner_repo", lambda: ("owner", "repo"))

    colors = render.Colors(commit="C", date="D", local="L", current="X", reset="R")

    # Test without PR info - should show commit subject
    out_no_pr = render.format_branch_info(
        "branch-name", "branch-name", False, colors, max_width=120
    )
    assert "original subject" in out_no_pr
    assert "#123" not in out_no_pr

    # Test with PR info - should show PR number and title instead of commit subject
    pr_info = ("123", "Add new feature")
    out_with_pr = render.format_branch_info(
        "branch-name", "branch-name", False, colors, max_width=120, pr_info=pr_info
    )
    assert "#123 Add new feature" in out_with_pr
    assert "original subject" not in out_with_pr


def test_format_branch_info_with_empty_pr_info(monkeypatch):
    # Test edge cases with PR info
    monkeypatch.setattr(
        render,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "commit subject"),
    )
    monkeypatch.setattr(render, "_detect_github_owner_repo", lambda: None)

    colors = render.Colors()

    # Test with None PR info
    out = render.format_branch_info("branch", "branch", False, colors, max_width=120, pr_info=None)
    assert "commit subject" in out

    # Test with empty strings in PR info tuple
    pr_info_empty = ("", "")
    out_empty = render.format_branch_info(
        "branch", "branch", False, colors, max_width=120, pr_info=pr_info_empty
    )
    assert "# " in out_empty  # Should show "# " even with empty values


def test_format_branch_info_worktree_coloring(monkeypatch):
    """Test that worktree branches use the same color as normal branches."""
    monkeypatch.setattr(
        render,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "feat: worktree branch"),
    )
    monkeypatch.setattr(render, "_detect_github_owner_repo", lambda: None)

    colors = render.Colors(
        local="\x1b[32m",  # green for normal branches
        current="\x1b[33m",  # yellow for current branch
        magenta="\x1b[35m",  # magenta (not used for worktrees anymore)
        reset="\x1b[0m",
        commit="\x1b[37m",
        date="\x1b[37m",
    )

    # Test normal branch (not worktree)
    out_normal = render.format_branch_info(
        "normal-branch", "normal-branch", False, colors, max_width=120, is_worktree=False
    )
    assert "\x1b[32mnormal-branch" in out_normal  # Should use local color (green)

    # Test worktree branch - should use same color as normal branch (local color)
    out_worktree = render.format_branch_info(
        "worktree-branch", "worktree-branch", False, colors, max_width=120, is_worktree=True
    )
    assert "\x1b[32mworktree-branch" in out_worktree  # Should use local color (green)

    # Test current branch (should still be current color even if worktree)
    out_current_worktree = render.format_branch_info(
        "current-branch", "current-branch", True, colors, max_width=120, is_worktree=True
    )
    assert "\x1b[33mcurrent-branch" in out_current_worktree  # Should use current color (yellow)
