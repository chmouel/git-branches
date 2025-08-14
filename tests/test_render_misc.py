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
    monkeypatch.setattr(render, "run", lambda cmd: types.SimpleNamespace(stdout="x\n"))
    assert render.git_log_oneline("ref", colors=None) == "x\n"

    # With colors and link building
    def _run(cmd, *a, **k):  # noqa: ANN001, D401
        return types.SimpleNamespace(stdout="aaaaaaaa aaaaaaa feat: subject\ninvalid line\n")

    monkeypatch.setattr(render, "run", _run)
    monkeypatch.setattr(render, "_detect_github_owner_repo", lambda: ("o", "r"))
    cols = render.Colors(commit="C", reset="R", feat="F")
    out = render.git_log_oneline("ref", n=1, colors=cols)
    assert "subject" in out and "https://github.com/o/r/commit/aaaaaaaa" in out
