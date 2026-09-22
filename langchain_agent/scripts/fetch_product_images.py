#!/usr/bin/env python3
"""Fetch product images for the scripted UI demos (#144).

The ESCI dataset ships no image column, so the demo UI had nothing to show
next to a product name. Amazon's legacy CDN, however, serves a product photo
keyed by ASIN -- and the ASIN is exactly the OpenSearch ``_id`` for every ESCI
product. That makes most demo images fetchable exactly, not approximated.

Two inputs, both committed so this is reproducible:

* ``scripts/demo_product_asins.json`` -- every product the four demos surface,
  captured by actually running them. ``named: true`` marks the ones the LLM
  speaks aloud on screen; those are the ones that matter most.
* ``scripts/demo_product_image_substitutes.json`` -- the curation layer. Some
  ASINs are delisted and have no image; this maps them to a *different* live
  ASIN (or a direct URL) for the same or a near-identical product.

Output is ``web/src/assets/products/<ASIN>.jpg`` plus a ``manifest.json``
recording where each image came from.

A miss is unambiguous: the CDN answers 200 with a 43-byte 1x1 GIF rather than
404, so we size-check instead of trusting the status code.

Usage::

    PYTHONPATH=. python scripts/fetch_product_images.py          # fetch
    PYTHONPATH=. python scripts/fetch_product_images.py --report # list misses only
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
SEED_FILE = SCRIPT_DIR / "demo_product_asins.json"
SUBSTITUTES_FILE = SCRIPT_DIR / "demo_product_image_substitutes.json"
OUT_DIR = PROJECT_DIR / "web" / "src" / "assets" / "products"
MANIFEST = OUT_DIR / "manifest.json"

CDN = "https://m.media-amazon.com/images/P/{}.01._SCLZZZZZZZ_.jpg"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# A miss is a 43-byte 1x1 transparent GIF served with HTTP 200. Anything this
# small is never a real product photo.
MIN_IMAGE_BYTES = 1000


def fetch(url: str) -> Optional[bytes]:
    """GET *url*, returning the body only if it looks like a real image."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as resp:
            body = resp.read()
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    return body if len(body) >= MIN_IMAGE_BYTES else None


def resolve(product: Dict, substitutes: Dict[str, str]) -> Tuple[Dict, Optional[bytes], Dict]:
    """Resolve one product to image bytes, preferring its own ASIN."""
    asin = product["asin"]

    body = fetch(CDN.format(asin))
    if body:
        return product, body, {"source": "exact", "source_url": CDN.format(asin)}

    sub = substitutes.get(asin)
    if sub:
        # A substitute is either another ASIN or an explicit image URL.
        url = sub if sub.startswith("http") else CDN.format(sub)
        body = fetch(url)
        if body:
            return product, body, {"source": "substitute", "source_url": url}

    return product, None, {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", action="store_true", help="report coverage without writing files"
    )
    args = parser.parse_args()

    if not SEED_FILE.exists():
        print(f"ERROR: missing seed file {SEED_FILE}", file=sys.stderr)
        return 1

    products: List[Dict] = json.loads(SEED_FILE.read_text())
    substitutes: Dict[str, str] = (
        json.loads(SUBSTITUTES_FILE.read_text()) if SUBSTITUTES_FILE.exists() else {}
    )
    # Allow comment keys in the substitutes file without them being treated as ASINs.
    substitutes = {k: v for k, v in substitutes.items() if not k.startswith("_")}

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda p: resolve(p, substitutes), products))

    if not args.report:
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, Dict] = {}
    misses: List[Dict] = []

    for product, body, origin in results:
        asin = product["asin"]
        if body is None:
            misses.append(product)
            continue
        if not args.report:
            (OUT_DIR / f"{asin}.jpg").write_bytes(body)
        manifest[asin] = {
            "title": product["title"],
            "named": product.get("named", False),
            **origin,
        }

    if not args.report:
        # Drop images for products no longer in the seed list, so the asset
        # directory never accumulates orphans. Scoped to *.jpg on purpose --
        # index.ts and manifest.json live here too and are not ours to delete.
        keep = {f"{p['asin']}.jpg" for p in products}
        for stale in OUT_DIR.glob("*.jpg"):
            if stale.name not in keep:
                stale.unlink()
                print(f"  removed stale {stale.name}")
        MANIFEST.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")

    total = len(products)
    named_total = sum(1 for p in products if p.get("named"))
    named_have = sum(1 for a, m in manifest.items() if m.get("named"))
    exact = sum(1 for m in manifest.values() if m["source"] == "exact")
    sub = sum(1 for m in manifest.values() if m["source"] == "substitute")

    print(f"\nimages: {len(manifest)}/{total}  (exact {exact}, substitute {sub})")
    print(f"named on screen: {named_have}/{named_total}")

    if misses:
        print(f"\n{len(misses)} product(s) still need a substitute -- add to")
        print(f'{SUBSTITUTES_FILE.relative_to(PROJECT_DIR)} as "<asin>": "<other-asin-or-url>":\n')
        for m in sorted(misses, key=lambda p: (not p.get("named"), p["title"])):
            flag = "NAMED" if m.get("named") else "     "
            print(f'  {flag}  "{m["asin"]}": "",  // {m["title"][:64]}')
    else:
        print("\nAll demo products have an image.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
