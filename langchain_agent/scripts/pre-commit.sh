#!/usr/bin/env bash
# Pre-commit: enforce black + isort formatting and flake8 lint on staged Python files.
# Mirrors ci-format + ci-lint steps in Makefile so CI never catches what local didn't.
#
# Installed by scripts/setup.sh as .git/hooks/pre-commit — do not run this
# directly against a clean checkout expecting it to do anything: it only
# acts on files that are actually staged.

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
VENV="$REPO_ROOT/langchain_agent/.venv/bin"

# Only check files that are actually staged. mapfile (not a bare $(...) split)
# so paths with spaces don't break the black/isort/flake8 invocations below.
mapfile -t STAGED < <(git diff --cached --name-only --diff-filter=ACM -- '*.py')
[ "${#STAGED[@]}" -eq 0 ] && exit 0

ABS_STAGED=()
for f in "${STAGED[@]}"; do
    ABS_STAGED+=("$REPO_ROOT/$f")
done

if [ ! -x "$VENV/black" ]; then
    echo "[pre-commit] $VENV not found or missing black/isort/flake8."
    echo "  Run: cd langchain_agent && ./scripts/setup.sh (or pip install -r requirements-dev.txt in .venv)"
    exit 1
fi

echo "[pre-commit] black --check ..."
"$VENV/black" --check "${ABS_STAGED[@]}" 2>&1 || {
  echo ""
  echo "  Run: cd langchain_agent && make format-fix"
  exit 1
}

echo "[pre-commit] isort --check-only ..."
"$VENV/isort" --check-only "${ABS_STAGED[@]}" 2>&1 || {
  echo ""
  echo "  Run: cd langchain_agent && make format-fix"
  exit 1
}

echo "[pre-commit] ✓ Formatting OK"

echo "[pre-commit] flake8 ..."
"$VENV/flake8" --config="$REPO_ROOT/langchain_agent/.flake8" "${ABS_STAGED[@]}" 2>&1 || {
  echo ""
  echo "  Fix the flake8 errors above, then re-stage and commit."
  exit 1
}

echo "[pre-commit] ✓ Lint OK"
