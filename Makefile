PROJECT_DIR := .
UV := uv run --project $(PROJECT_DIR) --quiet
PY_SRC := git_branch_list

.PHONY: install format lint fix test check run dev ci coverage clean

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

test-coverage:
	$(UV) pytest tests --cov=$(PY_SRC) --cov-report=term-missing --cov-report=html

check: lint test

run:
	$(UV) python -m git_branch_list.cli $(ARGS)

# Dev loop: lint (auto-fix), test, then format to keep code tidy
dev:
	$(UV) ruff check --fix $(PY_SRC) tests
	$(UV) pytest -q tests
	$(UV) ruff format $(PY_SRC) tests
	@command -v markdownlint >/dev/null 2>&1 && markdownlint --fix README.md || true

# CI-friendly aggregate target
ci: install lint test format

# Clean up generated files
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .pytest_cache/
	rm -rf __pycache__/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
