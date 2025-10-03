from __future__ import annotations

import types

from git_branch_list import fzf_ui


def test_confirm_variants(monkeypatch):
    # yes variants
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert fzf_ui.confirm("Proceed?") is True
    monkeypatch.setattr("builtins.input", lambda prompt: "YES")
    assert fzf_ui.confirm("Proceed?") is True
    # no / default
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert fzf_ui.confirm("Proceed?") is False
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert fzf_ui.confirm("Proceed?") is False

    # EOF returns False
    def _raise(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    assert fzf_ui.confirm("Proceed?") is False


def test_fzf_select_builds_command_and_parses(monkeypatch):
    calls: list[list[str]] = []

    class _P:
        def __init__(self, cmd, stdin=None, stdout=None, text=False):  # noqa: ANN001
            calls.append(cmd)
            self.stdin = types.SimpleNamespace(write=lambda s: None, close=lambda: None)
            # Simulate fzf returning selected lines, with both with/without tabs
            out_text = "shown1\tvalue1\nshown2\tvalue2\nno_tab_line\n"
            self._buf = types.SimpleNamespace(read=lambda: out_text)
            self.stdout = self._buf

        def wait(self):  # noqa: D401
            return 0

    monkeypatch.setattr(fzf_ui.subprocess, "Popen", _P)
    rows = [("S1", "v1"), ("S2", "v2")]
    sel = fzf_ui.fzf_select(
        rows,
        header="HDR",
        preview_cmd=["git", "log", "{2}"],
        multi=True,
        extra_binds=["alt-x:print-query"],
    )
    # Should parse values from fzf output (value1/value2 from simulated Popen)
    assert sel == ["value1", "value2"]
    # Command should include preview, header, multi, and binds
    cmd = calls[0]
    assert cmd[0] == "fzf"
    assert "--preview" in cmd
    assert "--footer" in cmd
    assert "--multi" in cmd
    assert cmd.count("--bind") == 1


def test_fzf_select_with_expect(monkeypatch):
    class _P:
        def __init__(self, cmd, stdin=None, stdout=None, text=False):  # noqa: ANN001
            self.cmd = cmd
            self.stdin = types.SimpleNamespace(write=lambda s: None, close=lambda: None)
            output = "alt-w\nshown\tvalue\n"
            self.stdout = types.SimpleNamespace(read=lambda: output)

        def wait(self):  # noqa: D401
            return 0

    monkeypatch.setattr(fzf_ui.subprocess, "Popen", _P)
    rows = [("Shown", "value")]
    key, values = fzf_ui.fzf_select(
        rows,
        header="hdr",
        preview_cmd=None,
        multi=False,
        extra_binds=None,
        expect_keys=["enter", "alt-w"],
    )
    assert key == "alt-w"
    assert values == ["value"]


def test_select_remote(monkeypatch):
    # Simulate git remote output and fzf selecting one
    class CP:
        def __init__(self, out):
            self.stdout = out

    monkeypatch.setattr(fzf_ui, "run", lambda cmd: CP("origin\nupstream\n"))  # noqa: ARG005

    class _P:
        def __init__(self, cmd, stdin=None, stdout=None, text=False):  # noqa: ANN001
            self._buf = types.SimpleNamespace(read=lambda: "upstream\n")
            self.stdin = types.SimpleNamespace(write=lambda s: None, close=lambda: None)
            self.stdout = self._buf

        def wait(self):  # noqa: D401
            return 0

    monkeypatch.setattr(fzf_ui.subprocess, "Popen", _P)
    assert fzf_ui.select_remote() == "upstream"
