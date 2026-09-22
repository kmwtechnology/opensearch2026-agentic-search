/**
 * ProductStrip - product photos for the items an answer actually names (#144).
 *
 * The ESCI catalog has no images, so before this the audience read product
 * names with nothing to look at. Photos are bundled by ASIN and resolved in
 * `selectProducts`; see that file for why matching is done on bold spans.
 *
 * Image coverage is partial by nature — a delisted ASIN has no photo. A
 * product without one is dropped from the strip rather than rendered as a
 * placeholder, so the demo never shows a broken tile.
 */

import type { Citation } from '../../stores/chatStore'
import { selectProducts } from './selectProducts'

interface ProductStripProps {
  content: string
  citations?: Citation[]
}

export function ProductStrip({ content, citations }: ProductStripProps) {
  const products = selectProducts(content, citations)
  if (products.length === 0) return null

  return (
    <div className="mt-4 flex flex-wrap gap-3" data-testid="product-strip">
      {products.map((product) => (
        <a
          key={product.asin}
          href={product.url}
          target="_blank"
          rel="noreferrer"
          title={product.title}
          className="group flex w-[9.5rem] flex-col gap-2 rounded-lg border-2 border-[var(--color-stage-border)] bg-white p-2 no-underline transition-colors hover:border-[#1E40AF] focus-visible:border-[#1E40AF] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1E40AF]"
        >
          <img
            src={product.image}
            alt={product.title}
            loading="lazy"
            className="h-[9rem] w-full rounded bg-white object-contain"
          />
          <span className="line-clamp-2 text-[1.25rem] leading-tight text-[var(--color-stage-ink)] group-hover:underline">
            {product.title}
          </span>
        </a>
      ))}
    </div>
  )
}
