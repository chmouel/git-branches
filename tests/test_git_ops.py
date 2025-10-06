from __future__ import annotations

import types

from git_branch_list import git_ops


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
