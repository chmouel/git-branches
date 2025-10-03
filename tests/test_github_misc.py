from __future__ import annotations

import json
import types

from git_branch_list import github, render


def _reset_github_caches():
    github._pr_cache.clear()  # noqa: SLF001
    github._pr_details_cache.clear()  # noqa: SLF001
    github._actions_cache.clear()  # noqa: SLF001
    github._actions_disk_loaded = False  # noqa: SLF001


def test_actions_status_icon_variants():
    colors = render.Colors(green="G", yellow="Y", red="R", cyan="C", magenta="M", reset="X")
    icon, label = github._actions_status_icon("success", "completed", colors)
    assert "G" in icon and label == "Success"
    icon, label = github._actions_status_icon("failure", "completed", colors)
    assert "R" in icon and label == "Failed"
    icon, label = github._actions_status_icon("cancelled", "completed", colors)
    assert "R" in icon and label == "Cancelled"
    icon, label = github._actions_status_icon("neutral", "completed", colors)
    assert "C" in icon and label == "Skipped"
    icon, label = github._actions_status_icon(None, "in_progress", colors)
    assert "Y" in icon and label == "In progress"
    icon, label = github._actions_status_icon(None, None, colors)
    assert label in {"Unknown", "None"}


def test_peek_actions_status_reads_disk(monkeypatch, tmp_path):
    _reset_github_caches()
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)
    monkeypatch.delenv("GIT_BRANCHES_NO_CACHE", raising=False)
    monkeypatch.delenv("GIT_BRANCHES_REFRESH", raising=False)
    monkeypatch.setenv("GIT_BRANCHES_SHOW_CHECKS", "1")
    data = {"deadbeef": {"timestamp": 1, "data": {"status": "completed", "conclusion": "success"}}}
    cache_file = tmp_path / "actions.json"
    cache_file.write_text(json.dumps(data))
    monkeypatch.setattr(github, "_actions_cache_file", lambda: str(cache_file))
    got = github.peek_actions_status_for_sha("deadbeef")
    assert got.get("conclusion") == "success"
    # unknown sha => {}
    assert github.peek_actions_status_for_sha("unknown") == {}


def test_get_actions_status_for_sha_fetch_and_cache(monkeypatch, tmp_path):
    _reset_github_caches()
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)
    monkeypatch.setenv("GIT_BRANCHES_SHOW_CHECKS", "1")
    monkeypatch.setattr(github, "detect_base_repo", lambda: ("o", "r"))

    class Resp:
        status_code = 200

        def json(self):
            return {
                "workflow_runs": [
                    {
                        "status": "completed",
                        "conclusion": "success",
                        "name": "CI",
                        "html_url": "https://example/run",
                        "id": 1,
                        "updated_at": "now",
                    }
                ]
            }

    monkeypatch.setattr(github, "_requests_get", lambda url, headers, timeout=3.0: Resp())
    monkeypatch.setattr(github, "_actions_cache_file", lambda: str(tmp_path / "actions.json"))
    out = github.get_actions_status_for_sha(("o", "r"), "deadbeef")
    assert out.get("name") == "CI"
    # subsequent call returns from cache
    out2 = github.get_actions_status_for_sha(("o", "r"), "deadbeef")
    assert out2.get("html_url") == "https://example/run"


def test_prefetch_actions_for_shas(monkeypatch):
    _reset_github_caches()
    monkeypatch.setenv("GIT_BRANCHES_SHOW_CHECKS", "1")
    calls: list[str] = []
    monkeypatch.setattr(github, "get_actions_status_for_sha", lambda base, sha: calls.append(sha))
    # non-tty to skip spinner
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)
    github.prefetch_actions_for_shas(("o", "r"), ["a", "b", "a", "c"], limit=2)
    # unique and limited
    assert set(calls).issubset({"a", "b", "c"})
    assert len(calls) <= 2


def test_get_pr_status_from_cache(monkeypatch):
    colors = render.Colors(green="G", yellow="Y", red="R", magenta="M", reset="X")
    _reset_github_caches()
    github._pr_cache.update(
        {  # noqa: SLF001
            "open": {"state": "open", "isDraft": False},
            "draft": {"state": "open", "isDraft": True},
            "closed": {"state": "closed"},
            "merged": {"state": "merged"},
        }
    )
    assert "G" in github.get_pr_status_from_cache("open", colors)
    assert "Y" in github.get_pr_status_from_cache("draft", colors)
    assert "R" in github.get_pr_status_from_cache("closed", colors)
    assert "M" in github.get_pr_status_from_cache("merged", colors)
    assert github.get_pr_status_from_cache("missing", colors) == ""


def test_detect_base_remote_prefers_upstream(monkeypatch):
    monkeypatch.setattr(
        github,
        "run",
        lambda cmd, check=True: types.SimpleNamespace(stdout="upstream\norigin\n"),
    )
    monkeypatch.setattr(
        github,
        "detect_github_repo",
        lambda remote: ("o", "r") if remote == "upstream" else None,
    )
    assert github.detect_base_remote() == ("upstream", "o", "r")


def test_detect_base_remote_fallback(monkeypatch):
    monkeypatch.setattr(
        github,
        "run",
        lambda cmd, check=True: types.SimpleNamespace(stdout="custom\n"),
    )
    monkeypatch.setattr(
        github,
        "detect_github_repo",
        lambda remote: ("o", "r") if remote == "custom" else None,
    )
    assert github.detect_base_remote() == ("custom", "o", "r")


def test_get_cached_pull_requests(monkeypatch):
    _reset_github_caches()
    monkeypatch.setattr(github, "_fetch_prs_and_populate_cache", lambda: None)
    github._pr_cache.update({"branch": {"number": 7}})  # noqa: SLF001
    assert github.get_cached_pull_requests() == [("branch", {"number": 7})]


def test_find_pr_for_ref_uses_details_cache(monkeypatch):
    _reset_github_caches()
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)
    monkeypatch.delenv("GIT_BRANCHES_NO_CACHE", raising=False)
    monkeypatch.delenv("GIT_BRANCHES_REFRESH", raising=False)
    github._pr_details_cache["branch"] = {  # noqa: SLF001
        "number": 7,
        "title": "My PR",
        "headRefOid": "abc",
        "state": "OPEN",
        "isDraft": False,
        "mergedAt": None,
        "body": "Hello",
        "baseRepository": {"owner": {"login": "o"}, "name": "r"},
        "labels": {"nodes": [{"name": "enhancement"}]},
        "reviewRequests": {"nodes": [{"requestedReviewer": {"login": "u1"}}]},
        "latestReviews": {"nodes": [{"author": {"login": "u2"}, "state": "APPROVED"}]},
    }
    # ref includes remote prefix; simulate git remote list to confirm normalization
    monkeypatch.setattr(
        github, "run", lambda cmd, check=True: types.SimpleNamespace(stdout="origin\n")
    )
    num, sha, state, title, draft, merged_at, base, labels, reqs, reviews, body = (
        github._find_pr_for_ref("origin/branch")
    )
    assert (num, sha, state, title, draft, merged_at) == ("7", "abc", "open", "My PR", False, "")
    assert base == ("o", "r")
    assert labels == ["enhancement"]
    assert reqs == ["u1"]
    assert reviews == {"u2": "APPROVED"}
    assert body == "Hello"


def test_prefetch_pr_details_populates_cache(monkeypatch):
    _reset_github_caches()
    monkeypatch.delenv("GIT_BRANCHES_OFFLINE", raising=False)
    monkeypatch.setenv("GIT_BRANCHES_NO_PROGRESS", "1")
    monkeypatch.setattr(github, "detect_base_repo", lambda: ("o", "r"))
    monkeypatch.setattr(github, "_github_token", lambda: "tok")
    # Remotes to strip prefixes
    monkeypatch.setattr(github, "run", lambda cmd: types.SimpleNamespace(stdout="origin\n"))

    class R:
        ok = True

        def json(self):
            # Return nodes for each alias r0/r1
            return {
                "data": {
                    "repository": {
                        "r0": {
                            "nodes": [
                                {
                                    "number": 1,
                                    "headRefName": "branch1",
                                    "author": {"login": "user1"},
                                }
                            ]
                        },
                        "r1": {
                            "nodes": [
                                {
                                    "number": 2,
                                    "headRefName": "branch2",
                                    "author": {"login": "user2"},
                                }
                            ]
                        },
                    }
                }
            }

    monkeypatch.setattr(github, "_requests_post", lambda url, headers, json, timeout=3.0: R())
    github.prefetch_pr_details(["origin/branch1", "branch2"], chunk_size=2)
    assert "branch1" in github._pr_details_cache  # noqa: SLF001
    assert "branch2" in github._pr_details_cache  # noqa: SLF001


def test_open_url_for_ref(monkeypatch):
    # happy path
    monkeypatch.setattr(
        github,
        "_find_pr_for_ref",
        lambda ref: ("5", "", "open", "", False, "", ("o", "r"), [], [], {}, ""),
    )
    opened = {"url": ""}
    monkeypatch.setattr("webbrowser.open", lambda url: opened.__setitem__("url", url))
    assert github.open_url_for_ref("branch") == 0
    assert opened["url"].endswith("/o/r/pull/5")
    # no PR
    monkeypatch.setattr(
        github, "_find_pr_for_ref", lambda ref: ("", "", "", "", False, "", None, [], [], {}, "")
    )
    assert github.open_url_for_ref("branch") == 1
