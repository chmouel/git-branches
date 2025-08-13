# git-branches

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](#requirements)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-46A3FF)](https://docs.astral.sh/ruff/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](../../LICENSE)

An interactive Git branch browser powered by fzf, with rich previews for GitHub PRs and CI status. It’s fast, keyboard-first, and designed for day-to-day workflows: jump to branches, spin up local tracking from remotes, open the PR in your browser, or prune branches in bulk.

## Highlights

- fzf-native UX: reverse list, previews, key bindings, multi-select for deletes.
- Rich preview: PR status (Open/Draft/Merged/Closed), OSC-8 link to the PR, CI combined status, and the last 10 commits with colors.
- GitHub awareness: shows whether a local branch exists on the remote (`-s`) and the CI status for the PR head commit.
- One-keystroke actions: checkout, open PR (`ctrl-o`), delete quickly (`alt-k`).

## Requirements

- git and fzf on PATH
- Python 3.12+ (uv-managed)
- Optional: `GITHUB_TOKEN` (improves rate limits and enables private repos)
- Optional: a Nerd Font for icons (fallback text is still readable)

## Installation

- Local dev via uv
  - `make install`
  - `make run` (or pass flags with `ARGS="..."`)
- System-wide (optional)
  - From this directory: `uv tool install .`
  - Then invoke the console script: `git-branches`

## Quickstart

- Browse and checkout local branches:
  - `make run`
- Browse remotes and checkout (creates tracking branch if needed):
  - `make run ARGS="-r"` (select remote interactively)
  - `make run ARGS="-R origin"`
- Deletion workflows:
  - `make run ARGS="-d"` (delete local; multi-select)
  - `make run ARGS="-D -R origin"` (delete remote)
- See if local branches exist on the remote:
  - `make run ARGS="-s"` (shows pushed status with default limit of 10)
  - `make run ARGS="-s -S"` (disable default limit)

## Command-line options

- `-r`: Browse remote branches (choose remote via fzf)
- `-R <remote>`: Browse a specific remote (e.g., origin)
- `-d`: Delete local branches (multi-select)
- `-D`: Delete remote branches (multi-select)
- `-s`: Show pushed status for local branches (GitHub API)
- `-n <N>`: Limit to first N branches
- `-S`: With `-s`, disable default limit (show all)
- `-C`: Disable colors
- `-l`: List-only mode (no checkout)

## Key bindings (fzf)

- `ctrl-o`: Open the PR for the highlighted ref in the default browser
- `alt-k`: Force-delete highlighted local branch (quick action)

## How it works

- Uses git for data (branch lists, recent commits) and fzf for the UI.
- Detects GitHub repository from the upstream of the current branch when possible, falling back to `origin` or the first remote.
- For `-s` and preview CI status, calls the GitHub API with `Authorization: Bearer $GITHUB_TOKEN` when set.

## Troubleshooting

- “fzf not found”: Install fzf and ensure it’s on PATH (`brew install fzf`, `apt install fzf`, etc.).
- “Not in a git repository”: Run within a git repo.
- No icons? Install a Nerd Font and configure your terminal to use it.
- Low API rate limit? Set `GITHUB_TOKEN` (a classic or fine-grained PAT works).

## Development

- Lint: `make lint` (auto-fix: `make fix`)
- Tests: `make test` (pytest)
- Dev loop: `make dev` (ruff fix → pytest → ruff format)
- Format: `make format` (ruff)

## Project layout

- `git_branch_list/`: core modules (`cli`, `git_ops`, `github`, `render`, `fzf_ui`)
- `tests/`: pytest test suite
- `pyproject.toml`: metadata and tool configuration
- `Makefile`: dev tasks

## License

See the repository’s `LICENSE` file.
