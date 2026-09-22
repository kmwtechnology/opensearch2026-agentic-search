/**
 * Picks which products an answer's photo strip should show (#144).
 *
 * The answer body names a handful of products in bold; the citation list
 * underneath carries up to ten. Showing a photo for all ten would contradict
 * the text the audience is reading, so we render only the products the answer
 * actually calls out, in the order it calls them out.
 *
 * Matching is by bold span rather than citation order because the LLM writes
 * the bolded name as a prefix of the full catalog title ("adidas Men's BB6622
 * Supernova Trail Shoe" for "adidas Men's BB6622 Supernova Trail Shoe, Hi-Res
 * Blue/Hi-Res Orange/Black - 10 M"). Verified against every turn of all four
 * demos: 15/15 bold spans resolved to the right citation.
 *
 * Lives apart from ProductStrip.tsx so that file only exports a component —
 * eslint's react-refresh rule runs at --max-warnings 0 here.
 */

import type { Citation } from '../../stores/chatStore'
import { getProductImage } from '../../assets/products'

/** Most tiles to show. Answers name ~3; this is headroom, not a target. */
export const MAX_TILES = 6

/** Strip the "[1] " / "[1,3] " index prefix the backend puts on every label. */
function citationTitle(label: string): string {
  return label.replace(/^\[[\d,]+\]\s*/, '')
}

/** Comparison key: case- and punctuation-insensitive, so "Men's" == "Mens". */
function normalize(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '')
}

export interface StripProduct {
  asin: string
  title: string
  url: string
  image: string
}

/**
 * Pick the products to show for an answer.
 *
 * `resolveImage` is injected so tests can run without Vite's asset pipeline.
 */
export function selectProducts(
  content: string,
  citations: Citation[] | undefined,
  resolveImage: (asin?: string) => string | undefined = getProductImage
): StripProduct[] {
  if (!citations?.length) return []

  const entries = citations.map((cite) => ({
    cite,
    title: citationTitle(cite.label),
  }))

  // Prefer the products the answer names, in the order it names them.
  const ordered: typeof entries = []
  for (const bold of content.matchAll(/\*\*(.+?)\*\*/g)) {
    const spoken = normalize(bold[1])
    if (!spoken) continue
    const match = entries.find((entry) => {
      const title = normalize(entry.title)
      return title.startsWith(spoken) || spoken.startsWith(title)
    })
    if (match && !ordered.includes(match)) ordered.push(match)
  }

  // An answer that names nothing in bold (a clarification, a summary) still
  // gets a strip, built from the top-ranked citations instead.
  const chosen = ordered.length > 0 ? ordered : entries

  const products: StripProduct[] = []
  for (const entry of chosen) {
    const image = resolveImage(entry.cite.asin)
    if (!image || !entry.cite.asin) continue
    products.push({
      asin: entry.cite.asin,
      title: entry.title,
      url: entry.cite.url,
      image,
    })
    if (products.length === MAX_TILES) break
  }
  return products
}
