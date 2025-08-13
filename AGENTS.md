# Repository Guidelines

## Project Structure & Module Organization
- Source: `git_branch_list/` — `cli.py` (entry), `git_ops.py` (git helpers), `fzf_ui.py` (fzf I/O), `github.py` (GitHub API), `render.py` (formatting).
- Tests: `tests/` — `test_git_branch_list.py`, `conftest.py`.
- Config: `pyproject.toml` (ruff, pytest, console script), `Makefile` (common tasks), `uv.lock`.
- Executable: console script `git-branches` (see `[project.scripts]`).

## Build, Test, and Development Commands
- `make install`: Install dev deps via uv.
- `make run ARGS="-r -n 20"`: Run the CLI locally.
- `make test`: Run pytest test suite.
- `make lint`: Lint with ruff; `make fix`: auto-fix with ruff.
- `make format`: Format with ruff.
- `make dev`: Fix → test → format (pre-push sanity).
- `make ci`: Aggregate target for CI parity.

## Coding Style & Naming Conventions
- Python 3.12; ruff is the single source of truth (line length 100, spaces indentation, quote style preserved).
- Modules/files: `snake_case`. Functions: `snake_case`. Classes: `PascalCase`. Constants: `UPPER_SNAKE_CASE`.
- Sort/import rules enforced by ruff. Run `make fix` then `make format` before committing.

## Testing Guidelines
- Framework: pytest. Place tests under `tests/` and name files `test_*.py`.
- Use `monkeypatch` to stub subprocess and network calls; avoid hitting real GitHub or git state.
- Run all tests with `make test`; run a single file with `uv run pytest -q tests/test_git_branch_list.py`.
- Add tests for CLI flags, local/remote flows, and GitHub status/preview rendering.

## Commit & Pull Request Guidelines
- Commits: imperative mood, concise scope, explain “why” and “what”. Prefer small, focused changes.
- PRs: clear description, linked issues, CLI usage examples (command and expected output snippet), note user-visible flags.
- All PRs must pass `make dev` locally before review.

## Security & Configuration Tips
- Runtime deps: `git` and `fzf` must be installed; the tool checks and exits if missing.
- GitHub API: set `GITHUB_TOKEN` (or store via `pass` as `github/$USER-token`) to improve rate limits. Never commit secrets.
