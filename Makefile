PROJECT_DIR := .
UV := uv run --project $(PROJECT_DIR) --quiet
PY_SRC := git_branch_list

.PHONY: install format lint fix test check run dev ci

install:
	uv sync --project $(PROJECT_DIR) --extra dev

format:
	$(UV) ruff format $(PY_SRC) tests

lint:
	$(UV) ruff check $(PY_SRC) tests

fix:
	$(UV) ruff check --fix $(PY_SRC) tests

test:
	$(UV) pytest -q tests

check: lint test

run:
	$(UV) python -m git_branch_list.cli $(ARGS)

# Dev loop: lint (auto-fix), test, then format to keep code tidy
dev:
	$(UV) ruff check --fix $(PY_SRC) tests
	$(UV) pytest -q tests
	$(UV) ruff format $(PY_SRC) tests

# CI-friendly aggregate target
ci: install lint test format
