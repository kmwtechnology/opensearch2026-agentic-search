#!/usr/bin/env bash
# Pre-commit: enforce black + isort formatting and flake8 lint on staged Python files.
# Mirrors ci-format + ci-lint steps in Makefile so CI never catches what local didn't.

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
VENV="$REPO_ROOT/langchain_agent/.venv/bin"

# Only check files that are actually staged
STAGED=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)
[ -z "$STAGED" ] && exit 0

# Make paths relative to repo root for black/isort
ABS_STAGED=$(echo "$STAGED" | xargs -I{} echo "$REPO_ROOT/{}")

echo "[pre-commit] black --check ..."
$VENV/black --check $ABS_STAGED 2>&1 || {
  echo ""
  echo "  Run: cd langchain_agent && make format-fix"
  exit 1
}

echo "[pre-commit] isort --check-only ..."
$VENV/isort --check-only $ABS_STAGED 2>&1 || {
  echo ""
  echo "  Run: cd langchain_agent && make format-fix"
  exit 1
}

echo "[pre-commit] ✓ Formatting OK"

echo "[pre-commit] flake8 ..."
$VENV/flake8 --config="$REPO_ROOT/langchain_agent/.flake8" $ABS_STAGED 2>&1 || {
  echo ""
  echo "  Fix the flake8 errors above, then re-stage and commit."
  exit 1
}

echo "[pre-commit] ✓ Lint OK"
