# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is `git-branches`, an interactive Git branch browser powered by fzf with GitHub integration. It's a Python CLI tool that provides rich previews for GitHub PRs and CI status, designed for efficient branch management workflows.

## Architecture

### Core Modules

- `git_branch_list/cli.py` - Command-line interface and argument parsing
- `git_branch_list/git_ops.py` - Git operations (branch listing, checkouts, deletions)
- `git_branch_list/fzf_ui.py` - fzf integration and user interaction
- `git_branch_list/github.py` - GitHub API integration for PR data and CI status
- `git_branch_list/render.py` - Output formatting and color handling
- `git_branch_list/progress.py` - Progress indicators and user feedback

### Key Features

- Interactive branch browsing with fzf
- GitHub PR status integration with caching
- CI status display via GitHub Actions API
- Multi-select branch deletion
- Remote branch tracking and checkout
- Performance optimizations with ETag caching

## Development Commands

### Essential Commands

- `make dev` - Main development loop: fix → test → format
- `make test` - Run pytest suite
- `make lint` - Lint code with ruff
- `make fix` - Auto-fix linting issues
- `make format` - Format code with ruff

### Testing

- `make coverage` - Run tests with coverage report (terminal + HTML)
- Tests are in `tests/` directory using pytest
- Test configuration in `pyproject.toml` with coverage settings

### Tool Setup

- Uses `uv` for dependency management
- Python 3.12+ required
- Ruff for linting and formatting (line length: 100)
- All commands run via `uv run` for isolation

### Running the Tool

- `make run ARGS='...'` - Run the CLI with arguments
- Always use `uv` like this `uv run git-branches` to run the program.

## Environment Variables

The tool supports several environment variables that affect behavior:

- `GIT_BRANCHES_OFFLINE=1` - Skip GitHub API calls
- `GIT_BRANCHES_NO_CACHE=1` - Bypass caching
- `GIT_BRANCHES_REFRESH=1` - Force cache refresh
- `GIT_BRANCHES_PREFETCH_DETAILS=1` - Batch GraphQL for PR details
- `GIT_BRANCHES_SHOW_CHECKS=1` - Allow fetching Actions status

## GitHub Integration

- Uses GitHub REST API for PR data
- Implements ETag-based caching in `~/.cache/git-branches/prs.json`
- Requires `GITHUB_TOKEN` for better rate limits and private repo access
- Batches API calls for performance

## Dependencies

- Core: `requests` for HTTP/GitHub API
- Dev: `pytest`, `ruff`, `pytest-cov`
- External: requires `git` and `fzf` on PATH
