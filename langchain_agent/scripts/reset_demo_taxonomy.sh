#!/usr/bin/env bash
#
# Re-arm the taxonomy demos. Both destroy their own preconditions: the correction demo
# rewrites the shipped tan->yellow mapping to brown, and the growth demo teaches the empty
# waterproof taxonomy a variant. Run either twice without resetting and turn 1 shows
# nothing wrong, with no error.
#
# Restores tan->yellow (re-tagging only the tan-listed products) and clears waterproof.
# Milliseconds. The UI's Restart button runs the same code via POST /api/admin/demo-reset.
#
# Usage: ./scripts/reset_demo_taxonomy.sh

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHONPATH=. .venv/bin/python -c "
import json
from quality.demo_reset import reset_demo_taxonomy

print(json.dumps(reset_demo_taxonomy(), indent=2))
"

echo
echo "Demos armed. 'show me tan boots' should now surface boots listed Tan but"
echo "indexed yellow, and pass the quality gate while doing it."
