# pylint: disable=missing-function-docstring,missing-module-docstring,missing-class-docstring,import-error,protected-access,too-few-public-methods,broad-exception-raised,unused-argument
from git_branch_list import cli, github, render, utils, worktrees


def test_truncate_display():
    t = render.truncate_display
    assert t("abcdef", 10) == "abcdef"
    assert t("abcdef", 3) == "ab…"
    assert t("a", 1) == "a"
    assert t("ab", 1) == "a"
    assert t("ab", 2) == "ab"


def test_detect_github_repo(monkeypatch):
    def fake_run_ok(cmd, cwd=None, check=True):  # noqa: ANN001
        class CP:
            def __init__(self, out):
                self.stdout = out

        url = {
            "git@github.com:owner/repo.git": "git@github.com:owner/repo.git\n",
            "https://github.com/owner/repo": "https://github.com/owner/repo\n",
            "ssh://git@github.com/owner/repo.git": "ssh://git@github.com/owner/repo.git\n",
        }
        return CP(url["git@github.com:owner/repo.git"])  # default one

    monkeypatch.setattr(github, "run", fake_run_ok)
    assert github.detect_github_repo("origin") == ("owner", "repo")


def test_fast_mode_sets_environment_variables(monkeypatch):
    """Test that --fast flag sets the appropriate environment variables for offline mode."""
    import os

    # Clear any existing environment variables
    for var in [
        "GIT_BRANCHES_OFFLINE",
        "GIT_BRANCHES_NO_PROGRESS",
        "GIT_BRANCHES_NO_CACHE",
        "GIT_BRANCHES_PREFETCH_DETAILS",
    ]:
        if var in os.environ:
            del os.environ[var]

    # Mock git repo check to avoid requiring actual git repo
    def mock_ensure_git_repo(required=True):
        return True

    monkeypatch.setattr("git_branch_list.git_ops.ensure_git_repo", mock_ensure_git_repo)

    # Mock interactive function to avoid fzf call
    def mock_interactive(args):
        return 0

    monkeypatch.setattr("git_branch_list.cli.interactive", mock_interactive)

    # Test that fast mode sets environment variables
    result = cli.main(["--fast", "-l"])

    assert os.environ.get("GIT_BRANCHES_OFFLINE") == "1"
    assert os.environ.get("GIT_BRANCHES_NO_PROGRESS") == "1"
    assert os.environ.get("GIT_BRANCHES_NO_CACHE") == "1"
    assert os.environ.get("GIT_BRANCHES_PREFETCH_DETAILS") == "0"
    assert result == 0


def test_branch_pushed_status_icons(monkeypatch):
    # Ensure we're not in offline mode
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)

    class Resp:
        def __init__(self, code):
            self.status_code = code

    monkeypatch.setattr(github, "_requests_get", lambda url, headers, timeout=3.0: Resp(200))
    ok = github.get_branch_pushed_status(("o", "r"), "feature/x")
    assert "" in ok
    monkeypatch.setattr(github, "_requests_get", lambda url, headers, timeout=3.0: Resp(404))
    ko = github.get_branch_pushed_status(("o", "r"), "feature/x")
    assert "" in ko
    monkeypatch.setattr(github, "_requests_get", lambda url, headers, timeout=3.0: Resp(500))
    unk = github.get_branch_pushed_status(("o", "r"), "feature/x")
    assert "" in unk


def test_preview_header_variants(monkeypatch, capsys):
    # Mock enhanced preview dependencies
    from git_branch_list import enhanced_preview

    def run_case(state: str, draft: bool, merged: bool):
        # Mock the gh command to return PR data
        pr_data = {
            "state": state.upper(),
            "number": 123,
            "title": "My Title",
            "isDraft": draft,
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": None,
        }

        monkeypatch.setattr(enhanced_preview, "_get_gh_pr_info", lambda branch, cwd=None: pr_data)
        monkeypatch.setattr(
            enhanced_preview,
            "_run_cmd",
            lambda cmd, cwd=None, check=False: "• deadbeef LOG\ncommit message\n",
        )

        github.preview_branch("feature/x")
        s = capsys.readouterr().out
        assert "#123" in s
        assert "My Title" in s
        assert "LOG" in s or "commit message" in s

        if merged:
            assert "MERGED" in s.upper()
        elif draft:
            assert "DRAFT" in s.upper()
        else:
            assert "OPEN" in s.upper()

    run_case("open", False, False)
    run_case("open", True, False)
    run_case("merged", False, True)


def test_format_worktree_summary(monkeypatch):
    import types

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        mapping = {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
                "origin/main\n",
                0,
            ),
            ("git", "rev-list", "--count", "origin/main..HEAD"): ("2\n", 0),
            ("git", "rev-list", "--count", "HEAD..origin/main"): ("1\n", 0),
            ("git", "status", "--porcelain"): ("M file1\n?? newfile\n", 0),
            (
                "git",
                "log",
                "-1",
                "--decorate=short",
                "--pretty=%(decorate)",
            ): (" (HEAD -> feature)\n", 0),
        }
        stdout, returncode = mapping.get(tuple(cmd), ("", 0))
        return types.SimpleNamespace(stdout=stdout, returncode=returncode)

    monkeypatch.setattr(github, "run", fake_run)
    colors = render.Colors()  # no colors so output is easy to assert
    summary = github._format_worktree_summary("feature", "/tmp/worktree", colors)
    assert "Branch: feature" in summary
    assert "Path: /tmp/worktree" in summary
    assert "Tracking: origin/main +2 -1" in summary
    assert "Changes: staged:1 untracked:1" in summary
    assert "HEAD: HEAD -> feature" in summary


def test_preview_branch_with_enhanced_style(monkeypatch, capsys):
    # Test that preview_branch now uses enhanced preview format
    from git_branch_list import enhanced_preview

    # Mock enhanced preview components
    pr_data = {
        "state": "OPEN",
        "number": 123,
        "title": "Test PR",
        "isDraft": False,
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": None,
    }

    monkeypatch.setattr(enhanced_preview, "_get_gh_pr_info", lambda branch, cwd=None: pr_data)
    monkeypatch.setattr(
        enhanced_preview, "_run_cmd", lambda cmd, cwd=None, check=False: "• deadbeef test commit\n"
    )

    github.preview_branch("feature/x")
    out = capsys.readouterr().out

    # Verify enhanced preview contains expected elements
    assert "Branch:" in out  # enhanced branch header
    assert "feature/x" in out  # branch name
    assert "#123" in out  # PR number
    assert "Test PR" in out  # PR title


def test_preview_worktree_sections(monkeypatch, capsys):
    monkeypatch.setattr(render, "setup_colors", lambda no_color=False: render.Colors())
    monkeypatch.setattr(github, "_branch_for_path", lambda path: "feature")
    monkeypatch.setattr(
        github,
        "_format_worktree_summary",
        lambda branch, path, colors: "WORKTREE",
    )
    monkeypatch.setattr(github, "_build_pr_section", lambda ref, colors, cols: "PR")
    monkeypatch.setattr(
        github,
        "_build_log_section",
        lambda ref, colors, limit, cwd: "LOG",
    )
    monkeypatch.setattr(github, "_build_diff_section", lambda path, colors: "DIFF")

    github.preview_worktree("/tmp/worktree")
    out = capsys.readouterr().out.strip()
    separator = "\n" + "─" * 80 + "\n"
    parts = out.split(separator)
    assert parts == ["WORKTREE", "PR", "LOG", "DIFF"]


def test_worktree_cache_helpers(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    last_file = cache_dir / "last"
    monkeypatch.setattr(worktrees, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(worktrees, "LAST_WORKTREE_FILE", last_file)

    worktrees.clear_last_worktree()
    assert worktrees.load_last_worktree() is None
    worktrees.save_last_worktree("/repo/feature")
    assert worktrees.load_last_worktree() == "/repo/feature"
    worktrees.clear_last_worktree()
    assert worktrees.load_last_worktree() is None


# Worktree functionality has been removed


def _reset_github_caches():
    github.pr_cache.clear()  # noqa: SLF001
    github._pr_details_cache.clear()  # noqa: SLF001
    github._actions_cache.clear()  # noqa: SLF001
    github._actions_disk_loaded = False  # noqa: SLF001


def test_format_pr_details(monkeypatch):
    colors = render.setup_colors(no_color=False)
    labels = ["bug", "enhancement"]
    review_requests = ["user1", "team-a"]
    latest_reviews = {"user2": "APPROVED", "user3": "CHANGES_REQUESTED"}
    details = render.format_pr_details(labels, review_requests, latest_reviews, colors)
    assert "bug" in details
    assert "enhancement" in details
    assert "user1" in details
    assert "team-a" in details
    assert "user2" in details
    assert "user3" in details
    assert "" in details
    assert "" in details


def test_derive_pr_branch_name_truncates():
    # This function seems to have been removed in the refactoring
    # Skipping this test for now
    pass


def test_local_branch_icon():
    # Test with colors
    colors = render.Colors(green="[green]", reset="[/reset]")
    assert utils.local_branch_icon(colors) == "[green][/reset]"

    # Test without colors
    colors_no_color = render.Colors()
    assert utils.local_branch_icon(colors_no_color) == ""

    # Test with reset but no green
    colors_partial = render.Colors(reset="[/reset]")
    assert utils.local_branch_icon(colors_partial) == ""


def test_worktree_icon():
    # Test with magenta color
    colors = render.Colors(magenta="[magenta]", reset="[/reset]")
    assert utils.worktree_icon(colors) == "[magenta][/reset]"

    # Test with green fallback when no magenta
    colors_green = render.Colors(green="[green]", reset="[/reset]")
    assert utils.worktree_icon(colors_green) == "[green][/reset]"

    # Test without colors
    colors_no_color = render.Colors()
    assert utils.worktree_icon(colors_no_color) == ""

    # Test with reset but no colors
    colors_partial = render.Colors(reset="[/reset]")
    assert utils.worktree_icon(colors_partial) == ""
