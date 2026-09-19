#!/usr/bin/env bash
# Build the application manual as an e-ink-tuned EPUB3.
# Requires: pandoc (brew install pandoc). Optional: epubcheck (brew install epubcheck).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/../agentic-hybrid-search-manual.md"
OUT="$HERE/agentic-hybrid-search-manual.epub"

pandoc "$SRC" \
  -f gfm -t epub3 --syntax-highlighting=none \
  --toc --toc-depth=3 --split-level=2 \
  --css "$HERE/epub-eink.css" \
  --lua-filter "$HERE/eink.lua" \
  --metadata title="Agentic Hybrid Search — Application Manual" \
  --metadata author="KMW Technology" \
  --metadata lang=en \
  --metadata date="$(date +%Y-%m-%d)" \
  -o "$OUT"

echo "wrote $OUT"
if command -v epubcheck >/dev/null; then
  epubcheck "$OUT"
fi
