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
    ns = p.parse_args(["-r", "-d", "-s", "-n", "5", "-C", "-l"])  # noqa: F841
    assert ns.remote_mode
    assert ns.delete_local
    assert ns.show_status
    assert ns.limit == 5
    assert ns.no_color
    assert ns.list_only


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
            ),
        )
        monkeypatch.setattr(github, "_commit_status_icon", lambda base, sha, colors: "[CI]")
        monkeypatch.setattr(github, "git_log_oneline", lambda ref, n=10, colors=None: "LOG\n")
        github.preview_branch("feature/x")
        s = capsys.readouterr().out
        assert "#123" in s
        assert "My Title" in s
        assert "LOG" in s
        if merged:
            assert "Merged" in s
        elif draft:
            assert "Draft" in s
        else:
            assert "Open" in s

    run_case("open", False, False)
    run_case("open", True, False)
    run_case("closed", False, True)


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


def test_commit_status_icon(monkeypatch):
    colors = render.Colors()

    class RespOK:
        ok = True

        def __init__(self, state):
            self._state = state

        def json(self):
            return {"state": self._state}

    monkeypatch.setattr(
        github, "_requests_get", lambda url, headers, timeout=3.0: RespOK("success")
    )
    assert "" in github._commit_status_icon(("o", "r"), "dead", colors)
    monkeypatch.setattr(
        github, "_requests_get", lambda url, headers, timeout=3.0: RespOK("failure")
    )
    assert "" in github._commit_status_icon(("o", "r"), "dead", colors)
    monkeypatch.setattr(
        github, "_requests_get", lambda url, headers, timeout=3.0: RespOK("pending")
    )
    assert "" in github._commit_status_icon(("o", "r"), "dead", colors)
    monkeypatch.setattr(github, "_requests_get", lambda url, headers, timeout=3.0: RespOK("weird"))
    assert "" in github._commit_status_icon(("o", "r"), "dead", colors)
