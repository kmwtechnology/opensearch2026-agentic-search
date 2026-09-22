/**
 * Bundled demo product images, keyed by ASIN (#144).
 *
 * The ESCI dataset ships no image column, so these are fetched once by
 * `scripts/fetch_product_images.py` and committed. Importing them through
 * `import.meta.glob` (rather than dropping them in `web/public/`) matters:
 * Vite content-hashes them into `dist/assets/`, which is the only directory
 * the FastAPI server actually mounts. Files in `public/` land at the `dist/`
 * root, where the SPA catch-all in `api/main.py` returns `index.html` for
 * them instead of the image.
 *
 * Coverage is deliberately partial — not every demo product still has a
 * photo on Amazon's by-ASIN CDN. Callers must treat a miss as normal.
 */

const modules = import.meta.glob('./*.jpg', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

/** ASIN -> bundled image URL. */
export const productImages: Record<string, string> = Object.fromEntries(
  Object.entries(modules).map(([path, url]) => [
    path.replace(/^\.\//, '').replace(/\.jpg$/, ''),
    url,
  ])
)

/** Resolve a product image by ASIN, or undefined when none is bundled. */
export function getProductImage(asin?: string): string | undefined {
  if (!asin) return undefined
  return productImages[asin]
}
