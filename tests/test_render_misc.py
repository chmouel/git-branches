from __future__ import annotations

import types

from git_branch_list import render


def test_get_git_color_and_setup_colors(monkeypatch):
    monkeypatch.setattr(render, "run", lambda cmd: types.SimpleNamespace(stdout="\x1b[31m\n"))
    assert render.get_git_color("color.branch.local", "normal") == "\x1b[31m"


def test_truncate_display():
    # Test basic truncation
    assert render.truncate_display("hello", 10) == "hello"
    assert render.truncate_display("hello", 3) == "he…"
    assert render.truncate_display("a", 1) == "a"
    assert render.truncate_display("ab", 1) == "a"
    assert render.truncate_display("ab", 2) == "ab"

    # Test edge cases
    assert render.truncate_display("", 5) == ""
    assert render.truncate_display("test", 0) == ""
    assert render.truncate_display("test", -1) == ""


def test_highlight_subject():
    colors = render.Colors(feat="[red]", fix="[green]", reset="[/reset]")

    # Test feat highlighting
    assert (
        render.highlight_subject("feat: add new feature", colors)
        == "[red]feat[/reset]: add new feature"
    )

    # Test fix highlighting
    assert render.highlight_subject("fix: bug fix", colors) == "[green]fix[/reset]: bug fix"

    # Test no highlighting for unknown types
    assert render.highlight_subject("chore: cleanup", colors) == "chore: cleanup"

    # Test with parentheses
    assert (
        render.highlight_subject("feat(api): new endpoint", colors)
        == "[red]feat(api)[/reset]: new endpoint"
    )


def test_osc8():
    # Test OSC8 hyperlink formatting
    result = render._osc8("https://github.com/user/repo", "click here")
    expected = "\x1b]8;;https://github.com/user/repo\x1b\\click here\x1b]8;;\x1b\\"
    assert result == expected

    # Test with empty URL
    result = render._osc8("", "text")
    expected = "\x1b]8;;\x1b\\text\x1b]8;;\x1b\\"
    assert result == expected
