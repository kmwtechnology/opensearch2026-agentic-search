/**
 * Looks up the catalog product a bold product name refers to (#144).
 *
 * An answer names a handful of products in bold; the citation list underneath
 * carries up to ten. Each named product becomes a card with its photo, so the
 * audience sees the item while reading about it — the citations that were
 * never named stay in the sources footer, unillustrated.
 *
 * Matching is by prefix in both directions because the LLM bolds a shortened
 * name ("adidas Men's BB6622 Supernova Trail Shoe") while the citation carries
 * the full catalog title (that, plus "Hi-Res Blue/Hi-Res Orange/Black - 10 M").
 *
 * Lives apart from the components so those files only export components —
 * eslint's react-refresh rule runs at --max-warnings 0 here.
 */

import type { Citation } from '../../stores/chatStore'
import { getProductImage } from '../../assets/products'

/** Strip the "[1] " / "[1,3] " index prefix the backend puts on every label. */
function citationTitle(label: string): string {
  return label.replace(/^\[[\d,]+\]\s*/, '')
}

/** Comparison key: case- and punctuation-insensitive, so "Men's" == "Mens". */
function normalize(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '')
}

export interface DemoProduct {
  asin: string
  /** Full catalog title, for the image's alt text and the link tooltip. */
  title: string
  url: string
  image: string
}

/** Resolve a bold product name to its card, or undefined when there is none. */
export type ProductLookup = (name: string) => DemoProduct | undefined

/**
 * Build the lookup for one answer.
 *
 * Citations with no ASIN (the image is keyed by it) and products with no
 * bundled photo are left out, so a hit always has something to show. Image
 * coverage is partial by nature — a delisted ASIN has no photo, and that
 * product simply stays a plain bullet.
 *
 * `resolveImage` is injected so tests can run without Vite's asset pipeline.
 */
export function indexProducts(
  citations: Citation[] | undefined,
  resolveImage: (asin?: string) => string | undefined = getProductImage
): ProductLookup {
  const entries: { key: string; product: DemoProduct }[] = []

  for (const cite of citations ?? []) {
    const image = resolveImage(cite.asin)
    if (!image || !cite.asin) continue
    const title = citationTitle(cite.label)
    entries.push({
      key: normalize(title),
      product: { asin: cite.asin, title, url: cite.url, image },
    })
  }

  if (entries.length === 0) return () => undefined

  return (name: string) => {
    const spoken = normalize(name)
    if (!spoken) return undefined
    return entries.find(
      (entry) => entry.key.startsWith(spoken) || spoken.startsWith(entry.key)
    )?.product
  }
}
