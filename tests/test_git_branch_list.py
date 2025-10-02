# pylint: disable=missing-function-docstring,missing-module-docstring,missing-class-docstring,import-error,protected-access,too-few-public-methods,broad-exception-raised,unused-argument
from git_branch_list import cli, git_ops, github, render, worktrees


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


def test_parser_flags():
    p = cli.build_parser()
    ns = p.parse_args(
        [
            "-r",
            "-d",
            "-s",
            "-n",
            "5",
            "-C",
            "-l",
            "--refresh",
            "--checks",
            "--fast",
            "--pr-only",
            "--worktree",
        ]
    )  # noqa: F841
    assert ns.remote_mode
    assert ns.delete_local
    assert ns.show_status
    assert ns.limit == 5
    assert ns.no_color
    assert ns.list_only
    assert ns.refresh
    assert ns.checks
    assert ns.fast
    assert ns.pr_only
    assert ns.worktree


def test_fast_mode_sets_environment_variables(monkeypatch):
    """Test that --fast flag sets the appropriate environment variables for offline mode."""
    import os

    from git_branch_list import cli

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


def test_collect_worktrees_sorting(monkeypatch):
    import types

    monkeypatch.delenv("GIT_BRANCHES_WORKTREE_BASEDIR", raising=False)
    monkeypatch.delenv("PM_BASEDIR", raising=False)

    listings = (
        "worktree /repo\n"
        "HEAD 1111111111111111111111111111111111111111\n"
        "branch refs/heads/main\n\n"
        "worktree /repo/feature\n"
        "HEAD 2222222222222222222222222222222222222222\n"
        "branch refs/heads/feature\n"
    )

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        key = (tuple(cmd), cwd)
        if key == (("git", "worktree", "list", "--porcelain"), None):
            return types.SimpleNamespace(stdout=listings, returncode=0)
        if key == (("git", "rev-parse", "--show-toplevel"), None):
            return types.SimpleNamespace(stdout="/repo\n", returncode=0)
        if key == (("git", "log", "-1", "--format=%ct|%h|%s", "HEAD"), "/repo"):
            return types.SimpleNamespace(
                stdout="1700000000|abc1234|feat: main commit\n", returncode=0
            )
        if key == (("git", "log", "-1", "--format=%ct|%h|%s", "HEAD"), "/repo/feature"):
            return types.SimpleNamespace(
                stdout="1700000500|def5678|fix: feature bug\n", returncode=0
            )
        if key == (("git", "status", "--porcelain"), "/repo"):
            return types.SimpleNamespace(stdout="", returncode=0)
        if key == (("git", "status", "--porcelain"), "/repo/feature"):
            return types.SimpleNamespace(stdout="M file1\n?? newfile\n", returncode=0)
        if key == (("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"), "/repo"):
            return types.SimpleNamespace(stdout="origin/main\n", returncode=0)
        if key == (
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"),
            "/repo/feature",
        ):
            return types.SimpleNamespace(stdout="origin/feature\n", returncode=0)
        if key == (("git", "rev-list", "--count", "origin/main..HEAD"), "/repo"):
            return types.SimpleNamespace(stdout="0\n", returncode=0)
        if key == (("git", "rev-list", "--count", "HEAD..origin/main"), "/repo"):
            return types.SimpleNamespace(stdout="0\n", returncode=0)
        if key == (("git", "rev-list", "--count", "origin/feature..HEAD"), "/repo/feature"):
            return types.SimpleNamespace(stdout="2\n", returncode=0)
        if key == (("git", "rev-list", "--count", "HEAD..origin/feature"), "/repo/feature"):
            return types.SimpleNamespace(stdout="1\n", returncode=0)
        return types.SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(worktrees, "run", fake_run)

    infos = worktrees.collect_worktrees()
    assert [wt.path for wt in infos] == ["/repo/feature", "/repo"]
    feature = infos[0]
    assert feature.branch == "feature"
    assert feature.dirty is True
    assert feature.ahead == 2
    assert feature.behind == 1
    assert feature.short_sha == "def5678"
    assert feature.commit_epoch == 1700000500


def test_collect_worktrees_from_basedir(monkeypatch, tmp_path):
    import types

    basedir = tmp_path / "trees"
    basedir.mkdir()
    (basedir / "mainrepo").mkdir()
    (basedir / "feature").mkdir()

    monkeypatch.setenv("GIT_BRANCHES_WORKTREE_BASEDIR", str(basedir))
    monkeypatch.setenv("PM_MAIN", "mainrepo")

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        key = (tuple(cmd), cwd)
        true = types.SimpleNamespace(stdout="true\n", returncode=0)
        empty = types.SimpleNamespace(stdout="", returncode=0)
        if key == (("git", "rev-parse", "--is-inside-work-tree"), str(basedir / "mainrepo")):
            return true
        if key == (("git", "rev-parse", "--is-inside-work-tree"), str(basedir / "feature")):
            return true
        if key == (("git", "rev-parse", "--abbrev-ref", "HEAD"), str(basedir / "mainrepo")):
            return types.SimpleNamespace(stdout="main\n", returncode=0)
        if key == (("git", "rev-parse", "--abbrev-ref", "HEAD"), str(basedir / "feature")):
            return types.SimpleNamespace(stdout="feature-branch\n", returncode=0)
        if key == (("git", "log", "-1", "--format=%ct|%h|%s", "HEAD"), str(basedir / "mainrepo")):
            return types.SimpleNamespace(
                stdout="1700000000|aaa1111|feat: main commit\n", returncode=0
            )
        if key == (("git", "log", "-1", "--format=%ct|%h|%s", "HEAD"), str(basedir / "feature")):
            return types.SimpleNamespace(
                stdout="1700000500|bbb2222|fix: feature bug\n", returncode=0
            )
        if key == (("git", "status", "--porcelain"), str(basedir / "mainrepo")):
            return empty
        if key == (("git", "status", "--porcelain"), str(basedir / "feature")):
            return types.SimpleNamespace(stdout="M file1\n", returncode=0)
        if key == (
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"),
            str(basedir / "mainrepo"),
        ):
            return types.SimpleNamespace(stdout="origin/main\n", returncode=0)
        if key == (
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"),
            str(basedir / "feature"),
        ):
            return types.SimpleNamespace(stdout="origin/feature\n", returncode=0)
        if key == (("git", "rev-list", "--count", "origin/main..HEAD"), str(basedir / "mainrepo")):
            return types.SimpleNamespace(stdout="0\n", returncode=0)
        if key == (("git", "rev-list", "--count", "HEAD..origin/main"), str(basedir / "mainrepo")):
            return types.SimpleNamespace(stdout="0\n", returncode=0)
        if key == (
            ("git", "rev-list", "--count", "origin/feature..HEAD"),
            str(basedir / "feature"),
        ):
            return types.SimpleNamespace(stdout="1\n", returncode=0)
        if key == (
            ("git", "rev-list", "--count", "HEAD..origin/feature"),
            str(basedir / "feature"),
        ):
            return types.SimpleNamespace(stdout="2\n", returncode=0)
        return empty

    monkeypatch.setattr(worktrees, "run", fake_run)

    infos = worktrees.collect_worktrees()
    assert [wt.name for wt in infos] == ["feature", "mainrepo"]
    feature = infos[0]
    assert feature.branch == "feature-branch"
    assert feature.dirty is True
    assert feature.short_sha == "bbb2222"
    assert feature.ahead == 1
    assert feature.behind == 2


def test_format_worktree_row(monkeypatch):
    monkeypatch.setattr(worktrees, "term_cols", lambda: 120)
    colors = render.Colors()
    info = worktrees.WorktreeInfo(
        path="/repo/feature",
        name="feature",
        branch="feature",
        short_sha="def5678",
        commit_epoch=1700000600,
        subject="fix: feature bug",
        dirty=True,
        tracking="origin/feature",
        ahead=3,
        behind=2,
        is_current=False,
    )
    row = worktrees.format_worktree_row(info, colors)
    assert "feature" in row
    assert "def5678" in row
    assert "dirty" in row
    assert "↑3" in row
    assert "↓2" in row
    assert "/repo/feature" in row


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
    github._pr_cache.clear()  # noqa: SLF001
    github._pr_details_cache.clear()  # noqa: SLF001
    github._actions_cache.clear()  # noqa: SLF001
    github._actions_disk_loaded = False  # noqa: SLF001


def test_find_pr_for_ref_graphql(monkeypatch):
    # Ensure we're not in offline mode and clear caches
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)
    _reset_github_caches()

    class Resp:
        ok = True

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    graphql_response = {
        "data": {
            "repository": {
                "pullRequests": {
                    "nodes": [
                        {
                            "number": 123,
                            "title": "GraphQL Test PR",
                            "headRefOid": "abcdef123",
                            "state": "OPEN",
                            "isDraft": False,
                            "mergedAt": None,
                            "body": "This is the PR body.",
                            "author": {"login": "test-author"},
                            "baseRepository": {
                                "owner": {"login": "test-owner"},
                                "name": "test-repo",
                            },
                            "labels": {"nodes": [{"name": "bug"}, {"name": "enhancement"}]},
                            "reviewRequests": {
                                "nodes": [
                                    {"requestedReviewer": {"login": "user1"}},
                                    {"requestedReviewer": {"name": "team-a"}},
                                ]
                            },
                            "latestReviews": {
                                "nodes": [
                                    {"author": {"login": "user2"}, "state": "APPROVED"},
                                    {
                                        "author": {"login": "user3"},
                                        "state": "CHANGES_REQUESTED",
                                    },
                                ]
                            },
                        }
                    ]
                }
            }
        }
    }

    # Mock the cache fetching to do nothing, so we use GraphQL
    monkeypatch.setattr(github, "_fetch_prs_and_populate_cache", lambda: None)
    monkeypatch.setattr(github, "detect_base_repo", lambda: ("test-owner", "test-repo"))
    monkeypatch.setattr(
        github,
        "_requests_post",
        lambda url, headers, json, timeout=3.0: Resp(graphql_response),
    )
    monkeypatch.setattr(
        github, "run", lambda cmd, check=True: type("CP", (), {"stdout": "origin\n"})()
    )

    (
        num,
        sha,
        state,
        title,
        draft,
        merged_at,
        pr_base,
        labels,
        review_requests,
        latest_reviews,
        body,
    ) = github._find_pr_for_ref("my-branch")

    assert num == "123"
    assert sha == "abcdef123"
    assert state == "open"
    assert title == "GraphQL Test PR"
    assert not draft
    assert not merged_at
    assert pr_base == ("test-owner", "test-repo")
    assert labels == ["bug", "enhancement"]
    assert review_requests == ["user1", "team-a"]
    assert latest_reviews == {"user2": "APPROVED", "user3": "CHANGES_REQUESTED"}
    assert body == "This is the PR body."


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


def test_remote_ssh_url(monkeypatch):
    class CP:
        def __init__(self, out):
            self.stdout = out

    monkeypatch.setattr(
        git_ops, "run", lambda cmd, cwd=None, check=True: CP("https://github.com/owner/repo.git\n")
    )
    assert git_ops.remote_ssh_url("origin") == "git@github.com:owner/repo.git"


def test_delete_local_flow(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_local_branches", lambda limit: ["b1", "b2"])  # noqa: ARG005
    monkeypatch.setattr(
        cli,
        "fzf_select",
        lambda rows, header, preview_cmd, multi=False, extra_binds=None: ["b1", "b2"],
    )  # noqa: ARG005
    monkeypatch.setattr(cli, "confirm", lambda prompt: True)  # noqa: ARG005

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        calls.append(cmd)

        class CP:
            stdout = ""

        return CP()

    monkeypatch.setattr(cli, "run", fake_run)
    args = cli.build_parser().parse_args(["-d"])  # delete local
    rc = cli.interactive(args)
    assert rc == 0
    assert any(c[:3] == ["git", "branch", "--delete"] for c in calls)


def test_delete_remote_flow(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_remote_branches", lambda remote, limit: ["r1", "r2"])  # noqa: ARG005
    monkeypatch.setattr(
        cli,
        "fzf_select",
        lambda rows, header, preview_cmd, multi=False, extra_binds=None: ["r1", "r2"],
    )  # noqa: ARG005
    monkeypatch.setattr(cli, "confirm", lambda prompt: True)  # noqa: ARG005
    monkeypatch.setattr(cli, "remote_ssh_url", lambda remote: "git@github.com:owner/repo.git")  # noqa: ARG005

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        calls.append(cmd)

        class CP:
            stdout = ""

        return CP()

    monkeypatch.setattr(cli, "run", fake_run)
    args = cli.build_parser().parse_args(["-D", "-R", "origin"])  # delete remote
    rc = cli.interactive(args)
    assert rc == 0
    push_deletes = [
        c
        for c in calls
        if c[:3] == ["git", "push", "--delete"] or (len(c) > 4 and c[2] == "--delete")
    ]
    assert len(push_deletes) >= 2
    assert any(c[:3] == ["git", "remote", "prune"] for c in calls)


def test_remote_checkout_tracking_creation(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_remote_branches", lambda remote, limit: ["feature"])  # noqa: ARG005
    monkeypatch.setattr(
        cli,
        "fzf_select",
        lambda rows, header, preview_cmd, multi=False, extra_binds=None: ["feature"],
    )  # noqa: ARG005

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        if cmd[:2] == ["git", "show-ref"]:
            raise Exception("not found")
        calls.append(cmd)

        class CP:
            stdout = ""

        return CP()

    monkeypatch.setattr(cli, "run", fake_run)
    args = cli.build_parser().parse_args(["-r", "-R", "origin"])
    rc = cli.interactive(args)
    assert rc == 0
    assert any(c[:3] == ["git", "checkout", "-b"] and c[-1] == "origin/feature" for c in calls)


def test_local_checkout(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_local_branches", lambda limit: ["feature"])  # noqa: ARG005
    monkeypatch.setattr(
        cli,
        "fzf_select",
        lambda rows, header, preview_cmd, multi=False, extra_binds=None: ["feature"],
    )  # noqa: ARG005

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        calls.append(cmd)

        class CP:
            stdout = ""

        return CP()

    monkeypatch.setattr(cli, "run", fake_run)
    args = cli.build_parser().parse_args([])
    rc = cli.interactive(args)
    assert rc == 0
    assert any(c[:2] == ["git", "checkout"] and c[-1] == "feature" for c in calls)


def test_local_checkout_worktree_detection(monkeypatch, capsys):
    """Test that worktree detection prevents checkout and prints worktree path."""
    calls = []
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_local_branches", lambda limit: ["feature"])  # noqa: ARG005
    monkeypatch.setattr(
        cli,
        "fzf_select",
        lambda rows, header, preview_cmd, multi=False, extra_binds=None: ["feature"],
    )  # noqa: ARG005
    monkeypatch.setattr(cli, "is_branch_in_worktree", lambda branch: True)
    monkeypatch.setattr(cli, "get_worktree_path", lambda branch: "/path/to/worktree")

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        calls.append(cmd)

        class CP:
            stdout = ""

        return CP()

    monkeypatch.setattr(cli, "run", fake_run)
    args = cli.build_parser().parse_args([])
    rc = cli.interactive(args)
    assert rc == 0
    # Should not have called git checkout
    assert not any(c[:2] == ["git", "checkout"] for c in calls)
    # Should have printed worktree path only
    captured = capsys.readouterr()
    assert captured.out.strip() == "/path/to/worktree"


def test_remote_checkout_worktree_detection(monkeypatch, capsys):
    """Test that worktree detection prevents remote checkout and prints worktree path."""
    calls = []
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_remote_branches", lambda remote, limit: ["feature"])  # noqa: ARG005
    monkeypatch.setattr(
        cli,
        "fzf_select",
        lambda rows, header, preview_cmd, multi=False, extra_binds=None: ["feature"],
    )  # noqa: ARG005
    monkeypatch.setattr(cli, "is_branch_in_worktree", lambda branch: True)
    monkeypatch.setattr(cli, "get_worktree_path", lambda branch: "/path/to/worktree")

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        calls.append(cmd)

        class CP:
            stdout = ""

        return CP()

    monkeypatch.setattr(cli, "run", fake_run)
    args = cli.build_parser().parse_args(["-r"])
    rc = cli.interactive(args)
    assert rc == 0
    # Should not have called git checkout
    assert not any(c[:2] == ["git", "checkout"] for c in calls)
    # Should have printed worktree path only
    captured = capsys.readouterr()
    assert captured.out.strip() == "/path/to/worktree"


def test_local_checkout_block_on_dirty(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_local_branches", lambda limit: ["feature"])  # noqa: ARG005
    monkeypatch.setattr(
        cli,
        "fzf_select",
        lambda rows, header, preview_cmd, multi=False, extra_binds=None: ["feature"],
    )  # noqa: ARG005
    monkeypatch.setattr(cli, "_is_workdir_dirty", lambda: True)

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        calls.append(cmd)

        class CP:
            stdout = ""

        return CP()

    monkeypatch.setattr(cli, "run", fake_run)
    args = cli.build_parser().parse_args([])
    rc = cli.interactive(args)
    assert rc == 1
    assert not any(c[:2] == ["git", "checkout"] for c in calls)


def test_remote_checkout_block_on_dirty_existing(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_remote_branches", lambda remote, limit: ["feature"])  # noqa: ARG005
    monkeypatch.setattr(
        cli,
        "fzf_select",
        lambda rows, header, preview_cmd, multi=False, extra_binds=None: ["feature"],
    )  # noqa: ARG005
    monkeypatch.setattr(cli, "_is_workdir_dirty", lambda: True)

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        # Simulate that branch exists locally for show-ref check
        class CP:
            stdout = ""

        calls.append(cmd)
        return CP()

    monkeypatch.setattr(cli, "run", fake_run)
    args = cli.build_parser().parse_args(["-r", "-R", "origin"])  # remote browse
    rc = cli.interactive(args)
    assert rc == 1
    assert not any(c[:2] == ["git", "checkout"] for c in calls)


def test_remote_checkout_block_on_dirty_create(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_remote_branches", lambda remote, limit: ["feature"])  # noqa: ARG005
    monkeypatch.setattr(
        cli,
        "fzf_select",
        lambda rows, header, preview_cmd, multi=False, extra_binds=None: ["feature"],
    )  # noqa: ARG005
    monkeypatch.setattr(cli, "_is_workdir_dirty", lambda: True)

    def fake_run(cmd, cwd=None, check=True):  # noqa: ANN001, ARG001
        # Make show-ref fail to force the create-tracking path
        if cmd[:2] == ["git", "show-ref"]:
            raise Exception("not found")

        class CP:
            stdout = ""

        calls.append(cmd)
        return CP()

    monkeypatch.setattr(cli, "run", fake_run)
    args = cli.build_parser().parse_args(["-r", "-R", "origin"])  # remote browse
    rc = cli.interactive(args)
    assert rc == 1
    # Ensure no checkout -b happened
    assert not any(c[:3] == ["git", "checkout", "-b"] for c in calls)


def test_build_rows_local_pr_only_filtering(monkeypatch):
    """Test that _build_rows_local correctly filters branches when pr_only=True."""

    # Clear offline mode to enable PR functionality
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)

    # Mock branch list
    monkeypatch.setattr(
        cli, "iter_local_branches", lambda limit: ["branch-with-pr", "branch-no-pr"]
    )
    monkeypatch.setattr(cli, "get_current_branch", lambda: "main")

    # Mock commit cache
    monkeypatch.setattr(
        cli,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "commit subject"),
    )

    # Mock GitHub functionality
    monkeypatch.setattr(github, "detect_base_repo", lambda: ("owner", "repo"))
    monkeypatch.setattr(github, "_fetch_prs_and_populate_cache", lambda: None)
    monkeypatch.setattr(cli, "build_last_commit_cache_for_refs", lambda refs: None)
    monkeypatch.setattr(github, "_checks_enabled", lambda: False)

    # Mock PR status - only return status for branch-with-pr
    def mock_get_pr_status(branch, colors):
        if branch == "branch-with-pr":
            return "🔀 PR #123"
        return ""

    monkeypatch.setattr(github, "get_pr_status_from_cache", mock_get_pr_status)

    # Mock PR cache to simulate branches with/without PRs
    github._pr_cache = {"branch-with-pr": {"number": 123, "title": "Test PR"}}

    colors = render.Colors()

    # Test with pr_only=False - should return both branches
    rows_all = cli._build_rows_local(False, None, colors, pr_only=False)
    assert len(rows_all) == 2
    branch_names = [row[1] for row in rows_all]
    assert "branch-with-pr" in branch_names
    assert "branch-no-pr" in branch_names

    # Test with pr_only=True - should only return branch with PR
    rows_pr_only = cli._build_rows_local(False, None, colors, pr_only=True)
    assert len(rows_pr_only) == 1
    assert rows_pr_only[0][1] == "branch-with-pr"

    # Clean up
    github._pr_cache.clear()


def test_build_rows_local_with_pr_info_display(monkeypatch):
    """Test that _build_rows_local correctly displays PR info in branch rows."""

    # Clear offline mode to enable PR functionality
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)

    # Mock branch list
    monkeypatch.setattr(cli, "iter_local_branches", lambda limit: ["test-branch"])
    monkeypatch.setattr(cli, "get_current_branch", lambda: "main")

    # Mock commit cache
    monkeypatch.setattr(
        cli,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "original commit subject"),
    )

    # Mock GitHub functionality
    monkeypatch.setattr(github, "detect_base_repo", lambda: ("owner", "repo"))
    monkeypatch.setattr(github, "_fetch_prs_and_populate_cache", lambda: None)
    monkeypatch.setattr(cli, "build_last_commit_cache_for_refs", lambda refs: None)
    monkeypatch.setattr(github, "_checks_enabled", lambda: False)
    monkeypatch.setattr(github, "get_pr_status_from_cache", lambda branch, colors: "")

    # Mock PR cache with test data
    github._pr_cache = {"test-branch": {"number": 456, "title": "Amazing new feature"}}

    colors = render.Colors()

    # Test that PR info is displayed instead of commit subject
    rows = cli._build_rows_local(False, None, colors, pr_only=False)
    assert len(rows) == 1
    row_display = rows[0][0]

    # Should contain PR number and title
    assert "#456 Amazing new feature" in row_display
    # Should NOT contain original commit subject
    assert "original commit subject" not in row_display

    # Clean up
    github._pr_cache.clear()


def test_build_rows_local_fast_mode_pr_only(monkeypatch):
    """Test that pr_only filtering is disabled in fast mode."""

    # Set offline mode to enable fast mode
    monkeypatch.setenv("GIT_BRANCHES_OFFLINE", "1")

    # Mock branch list
    monkeypatch.setattr(cli, "iter_local_branches", lambda limit: ["branch1", "branch2"])
    monkeypatch.setattr(cli, "get_current_branch", lambda: "main")

    # Mock commit cache
    monkeypatch.setattr(
        cli,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "commit subject"),
    )

    monkeypatch.setattr(cli, "build_last_commit_cache_for_refs", lambda refs: None)

    colors = render.Colors()

    # Even with pr_only=True, should return all branches in fast mode
    rows = cli._build_rows_local(False, None, colors, pr_only=True)
    assert len(rows) == 2
    branch_names = [row[1] for row in rows]
    assert "branch1" in branch_names
    assert "branch2" in branch_names


def test_build_rows_remote_with_pr_info_display(monkeypatch):
    """Test that _build_rows_remote correctly displays PR info in remote branch rows."""

    # Clear offline mode to enable PR functionality
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)

    # Mock remote branch list
    monkeypatch.setattr(cli, "iter_remote_branches", lambda remote, limit: ["test-remote-branch"])

    # Mock commit cache
    monkeypatch.setattr(
        cli,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "original commit subject"),
    )

    # Mock GitHub functionality
    monkeypatch.setattr(github, "detect_base_repo", lambda: ("owner", "repo"))
    monkeypatch.setattr(github, "_fetch_prs_and_populate_cache", lambda: None)
    monkeypatch.setattr(cli, "build_last_commit_cache_for_refs", lambda refs: None)
    monkeypatch.setattr(github, "_checks_enabled", lambda: False)
    monkeypatch.setattr(github, "get_pr_status_from_cache", lambda branch, colors: "")

    # Mock PR cache with test data
    github._pr_cache = {"test-remote-branch": {"number": 789, "title": "Remote branch feature"}}

    colors = render.Colors()

    # Test that PR info is displayed instead of commit subject for remote branches
    rows = cli._build_rows_remote("origin", None, colors)
    assert len(rows) == 1
    row_display = rows[0][0]

    # Should contain PR number and title
    assert "#789 Remote branch feature" in row_display
    # Should NOT contain original commit subject
    assert "original commit subject" not in row_display

    # Clean up
    github._pr_cache.clear()


def test_build_rows_remote_fast_mode(monkeypatch):
    """Test that _build_rows_remote works correctly in fast mode."""

    # Set offline mode to enable fast mode
    monkeypatch.setenv("GIT_BRANCHES_OFFLINE", "1")

    # Mock remote branch list
    monkeypatch.setattr(cli, "iter_remote_branches", lambda remote, limit: ["remote1", "remote2"])

    # Mock commit cache
    monkeypatch.setattr(
        cli,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "commit subject"),
    )

    monkeypatch.setattr(cli, "build_last_commit_cache_for_refs", lambda refs: None)

    colors = render.Colors()

    # Should return all remote branches in fast mode without PR processing
    rows = cli._build_rows_remote("origin", None, colors)
    assert len(rows) == 2
    branch_names = [row[1] for row in rows]
    assert "remote1" in branch_names
    assert "remote2" in branch_names


def test_interactive_pr_only_toggle_command_generation(monkeypatch):
    """Test that the Alt-p toggle command is correctly generated for PR-only mode."""

    # Mock dependencies to avoid actual fzf execution
    monkeypatch.setattr(cli, "ensure_deps", lambda interactive=True: None)
    monkeypatch.setattr(cli, "iter_local_branches", lambda limit: ["test-branch"])
    monkeypatch.setattr(cli, "get_current_branch", lambda: "main")
    monkeypatch.setattr(cli, "get_last_commit_from_cache", lambda ref: None)
    monkeypatch.setattr(cli, "build_last_commit_cache_for_refs", lambda refs: None)
    monkeypatch.setattr(github, "detect_base_repo", lambda: None)
    monkeypatch.setattr(github, "_fetch_prs_and_populate_cache", lambda: None)
    monkeypatch.setattr(github, "_checks_enabled", lambda: False)
    monkeypatch.setattr(github, "get_pr_status_from_cache", lambda branch, colors: "")

    # Capture the fzf_select call to inspect the bindings
    captured_calls = []

    def mock_fzf_select(rows, header, preview_cmd, multi=False, extra_binds=None):
        captured_calls.append({"rows": rows, "header": header, "extra_binds": extra_binds})
        return []  # Cancel selection

    monkeypatch.setattr(cli, "fzf_select", mock_fzf_select)

    # Test with pr_only=False - toggle command should add --pr-only
    args = cli.build_parser().parse_args(["-s", "-n", "5"])  # show_status=True, limit=5
    cli.interactive(args)

    assert len(captured_calls) == 1
    bindings = captured_calls[0]["extra_binds"]

    # Find the alt-p binding
    alt_p_binding = None
    for binding in bindings:
        if binding.startswith("alt-p:reload("):
            alt_p_binding = binding
            break

    assert alt_p_binding is not None
    # Should contain --pr-only since we're not currently in PR-only mode
    assert "--pr-only" in alt_p_binding
    assert "-s" in alt_p_binding  # Should preserve show_status
    assert "-n 5" in alt_p_binding  # Should preserve limit

    # Reset for next test
    captured_calls.clear()

    # Test with pr_only=True - toggle command should NOT add --pr-only
    args = cli.build_parser().parse_args(["--pr-only", "-s", "-n", "5"])
    cli.interactive(args)

    assert len(captured_calls) == 1
    bindings = captured_calls[0]["extra_binds"]

    # Find the alt-p binding
    alt_p_binding = None
    for binding in bindings:
        if binding.startswith("alt-p:reload("):
            alt_p_binding = binding
            break

    assert alt_p_binding is not None
    # Should NOT contain --pr-only since we're currently in PR-only mode
    assert "--pr-only" not in alt_p_binding
    assert "-s" in alt_p_binding  # Should preserve show_status
    assert "-n 5" in alt_p_binding  # Should preserve limit


def test_build_rows_local_worktree_filtering(monkeypatch):
    """Test that _build_rows_local correctly filters branches when worktree=True."""

    # Clear offline mode to enable worktree functionality
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)

    # Mock branch list
    monkeypatch.setattr(
        cli, "iter_local_branches", lambda limit: ["branch-with-worktree", "branch-no-worktree"]
    )
    monkeypatch.setattr(cli, "get_current_branch", lambda: "main")

    # Mock commit cache
    monkeypatch.setattr(
        cli,
        "get_last_commit_from_cache",
        lambda ref: ("1700000000", "f" * 40, "deadbee", "commit subject"),
    )

    # Mock GitHub functionality
    monkeypatch.setattr(github, "detect_base_repo", lambda: ("owner", "repo"))
    monkeypatch.setattr(github, "_fetch_prs_and_populate_cache", lambda: None)
    monkeypatch.setattr(cli, "build_last_commit_cache_for_refs", lambda refs: None)
    monkeypatch.setattr(github, "_checks_enabled", lambda: False)
    monkeypatch.setattr(github, "get_pr_status_from_cache", lambda branch, colors: "")

    # Mock worktree detection - only branch-with-worktree has a worktree
    def mock_is_branch_in_worktree(branch):
        return branch == "branch-with-worktree"

    monkeypatch.setattr(cli, "is_branch_in_worktree", mock_is_branch_in_worktree)

    colors = render.Colors()

    # Test with worktree=False - should return both branches
    rows_all = cli._build_rows_local(False, None, colors, worktree=False)
    assert len(rows_all) == 2
    branch_names = [row[1] for row in rows_all]
    assert "branch-with-worktree" in branch_names
    assert "branch-no-worktree" in branch_names

    # Test with worktree=True - should only return branch with worktree
    rows_worktree_only = cli._build_rows_local(False, None, colors, worktree=True)
    assert len(rows_worktree_only) == 1
    assert rows_worktree_only[0][1] == "branch-with-worktree"
