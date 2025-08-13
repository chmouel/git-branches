# pylint: disable=missing-function-docstring,missing-module-docstring,missing-class-docstring,import-error,protected-access,too-few-public-methods,broad-exception-raised,unused-argument
from git_branch_list import cli, git_ops, github, render


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


def test_branch_pushed_status_icons(monkeypatch):
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
    # Avoid git config lookups for colors in preview
    monkeypatch.setattr(render, "setup_colors", lambda no_color=False: render.Colors())

    def run_case(state: str, draft: bool, merged: bool):
        monkeypatch.setattr(
            github,
            "_find_pr_for_ref",
            lambda ref: (
                "123",
                "deadbeef",
                state,
                "My Title",
                draft,
                "now" if merged else "",
                ("owner", "repo"),
                [],
                [],
                {},
                "PR Body",
            ),
        )
        monkeypatch.setattr(github, "git_log_oneline", lambda ref, n=10, colors=None: "LOG\n")
        github.preview_branch("feature/x")
        s = capsys.readouterr().out
        assert "#123" in s
        assert "My Title" in s
        assert "LOG" in s
        assert "PR Body" in s
        if merged:
            assert "Merged" in s
        elif draft:
            assert "Draft" in s
        else:
            assert "Open" in s

    run_case("open", False, False)
    run_case("open", True, False)
    run_case("closed", False, True)


def test_find_pr_for_ref_graphql(monkeypatch):
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
