# Agent Guidelines for this Repository

This repository uses a Python uv-script and package for `git-branches` with fzf integration. When making changes, follow these rules to keep contributions consistent and tidy.

Development rules

- Always run `make dev` before pushing changes. It performs:
  - `ruff check --fix` to auto-fix common issues
  - `pytest` to run the test suite
  - `ruff format` to format code
- Prefer small, focused changes that preserve existing behavior unless the task specifies otherwise.
- Keep CI and local workflows aligned by using the Makefile targets defined at the repo root.

Formatting and linting

- Ruff is the single source of truth for formatting and linting.
- Always ensure code is formatted with `ruff format` after any code change.
- Lint locally with `make lint`; auto-fix with `make fix`.

How to run things

- Install dev dependencies: `make install`
- Run the tool: `make run` (delegates to the `git-branches` console script)
- Run tests: `make test`
- Full dev loop: `make dev`

Package layout

- Python package lives under `git/git-branches`:
  - Source: `git_branch_list/`
  - Tests: `tests/`
  - Config: `pyproject.toml` with tool configuration (`ruff`, `pytest` optional dep)
