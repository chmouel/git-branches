# Project configuration
PROJECT_DIR := .
UV := uv run --project $(PROJECT_DIR) --quiet
PY_SRC := git_branch_list

# Tools
RUFF := $(UV) ruff
PYTEST := $(UV) pytest

# ANSI color codes
YELLOW  := \033[0;33m
CYAN    := \033[0;36m
BOLD    := \033[1m
RESET   := \033[0m

.PHONY: help install format lint fix test check run dev ci coverage clean brew-local

# Default target
help: ## Show this help message
	@echo ""
	@echo "$(BOLD)$(CYAN)🎯 Makefile — Git Branch List Tool$(RESET)"
	@echo ""
	@echo "$(BOLD)Available targets:$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		sort | \
		awk 'BEGIN {FS = ":.*?## "} {printf "  $(CYAN)%-18s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# --- Development & Testing ---

install: ## 📦 Install project dependencies (with dev extras)
	uv sync --project $(PROJECT_DIR) --extra dev

format: ## 🧹 Format Python code using ruff
	$(RUFF) format $(PY_SRC) tests

lint: ## 🔍 Lint Python code (no fixes)
	$(RUFF) check $(PY_SRC) tests

fix: ## 🔧 Fix linting issues automatically
	$(RUFF) check --fix $(PY_SRC) tests

test: ## ✅ Run tests quietly
	$(PYTEST) -q tests

coverage: ## 📊 Run tests with coverage report (terminal + HTML)
	$(PYTEST) tests --cov=$(PY_SRC) --cov-report=term-missing --cov-report=html

check: ## 🧪 Run linting and tests
	lint test

run: ## ▶️  Run the CLI tool (pass ARGS='...' for arguments)
	$(UV) python -m git_branch_list.cli $(ARGS)

dev: ## 🔁 Dev loop: fix → test → format + markdown lint
	$(RUFF) check --fix $(PY_SRC) tests
	$(PYTEST) -q tests
	$(RUFF) format $(PY_SRC) tests
	@command -v markdownlint >/dev/null 2>&1 && markdownlint --fix README.md || true

# --- CI & Maintenance ---

ci: ## 🤖 CI-friendly: install, check, and format
	install check format

clean: ## 🧽 Remove build artifacts and cache files
	rm -rf build/ dist/ *.egg-info/ htmlcov/ .coverage .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# --- Packaging ---

brew-local: ## 🍺 Create local Homebrew tap and install --HEAD
	$(eval TAP ?= $(shell git config user.name)/git-branches-dev)
	@echo "$(YELLOW)Using tap: $(TAP)$(RESET)"
	@set -e; \
	brew tap-new "$(TAP)" >/dev/null 2>&1 || true; \
	TAP_DIR="$$(brew --repo "$(TAP)")"; \
	mkdir -p "$$TAP_DIR/Formula"; \
	cp Formula/git-branches.rb "$$TAP_DIR/Formula/"; \
	brew install --HEAD "$(TAP)/git-branches" || brew reinstall --HEAD "$(TAP)/git-branches"
