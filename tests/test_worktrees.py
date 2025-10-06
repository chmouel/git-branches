from __future__ import annotations

from pathlib import Path

from git_branch_list import worktrees


def test_sort_key():
    # Test sorting key for worktree info
    info_clean = worktrees.WorktreeInfo(
        path="/path/clean",
        name="clean",
        branch="main",
        short_sha="abc123",
        commit_epoch=1700000000,
        subject="clean commit",
        dirty=False,
        tracking="origin/main",
        ahead=0,
        behind=0,
        is_current=False,
    )

    info_dirty = worktrees.WorktreeInfo(
        path="/path/dirty",
        name="dirty",
        branch="feature",
        short_sha="def456",
        commit_epoch=1700000500,
        subject="dirty commit",
        dirty=True,
        tracking="origin/feature",
        ahead=1,
        behind=2,
        is_current=False,
    )

    # Clean worktrees should sort before dirty ones
    assert worktrees._sort_key(info_clean) > worktrees._sort_key(info_dirty)

    # Within same cleanliness, newer commits sort first (higher epoch = lower sort key)
    assert worktrees._sort_key(info_dirty) < worktrees._sort_key(info_clean)


def test_load_save_clear_last_worktree(tmp_path):
    # Test saving and loading last worktree
    test_path = "/some/test/path"

    # Clear any existing last worktree first
    worktrees.clear_last_worktree()

    # Initially should return None
    assert worktrees.load_last_worktree() is None

    # Save a path
    worktrees.save_last_worktree(test_path)

    # Should be able to load it back
    assert worktrees.load_last_worktree() == test_path

    # Clear it
    worktrees.clear_last_worktree()

    # Should be None again
    assert worktrees.load_last_worktree() is None


def test_get_cache_dir():
    # Test cache directory resolution
    cache_dir = worktrees._get_cache_dir()
    assert isinstance(cache_dir, Path)
    assert "git-branches" in str(cache_dir)
