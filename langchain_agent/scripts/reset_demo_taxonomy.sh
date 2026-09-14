#!/usr/bin/env bash
#
# Put the taxonomy self-correction demo back to its "before" state (#103).
#
# The demo destroys its own preconditions: it works because the catalog
# mis-tags tan products as yellow, and succeeding rewrites that mapping to
# brown and re-indexes every product to match. Run it twice without resetting
# and turn 1 shows nothing wrong — no mismatch to spot, nothing to dispute.
# It does not error, it just quietly stops demonstrating anything.
#
# Default is the FAST path: flip the mapping row and re-tag only the products
# actually listed as tan. Milliseconds. Pass --full to re-run the real Lucille
# ingest over all 9,618 products instead (~20s), for when the index may have
# drifted for reasons beyond this demo.
#
# The Restart button in the UI calls the same code path via
# POST /api/admin/demo-reset.
#
# Usage: ./scripts/reset_demo_taxonomy.sh [--full]   (or: make demo-reset)

set -euo pipefail

cd "$(dirname "$0")/.."

FULL="False"
if [ "${1:-}" = "--full" ]; then
  FULL="True"
  echo "==> Full reset: mapping + complete re-ingest (~20s)"
else
  echo "==> Fast reset: mapping + re-tag tan-listed products"
fi

PYTHONPATH=. .venv/bin/python -c "
import json
from quality.demo_reset import reset_demo_taxonomy
result = reset_demo_taxonomy(full_reindex=${FULL})
print(json.dumps(result, indent=2))
if result.get('error'):
    raise SystemExit('reset reported an error: ' + str(result['error']))
"

echo
echo "Demo is armed. 'show me tan boots' should now surface boots listed Tan but"
echo "indexed yellow, and pass the quality gate while doing it."
