/**
 * ProductCard - one named product, rendered the way a shopper expects (#144).
 *
 * The ESCI catalog has no images, so before this the audience read a bullet
 * list of product names with nothing to look at. Rather than hang a row of
 * photos off the bottom of the answer, each bullet the answer names becomes a
 * card: photo on the left, the name and the model's own blurb on the right.
 * The description is the list item's markdown, passed straight through, so
 * whatever the LLM wrote still renders as written.
 *
 * Only the photo links out. The name sits in `children` as a <strong>, and
 * wrapping the text in a second anchor would underline the whole blurb
 * (`.markdown-content a` in index.css) and give the card two links to the
 * same place. Every product is also a text link in the sources footer.
 */

import type { ReactNode } from 'react'
import type { DemoProduct } from './productIndex'

interface ProductCardProps {
  product: DemoProduct
  /** The list item's own markdown: the bold product name plus its blurb. */
  children: ReactNode
}

export function ProductCard({ product, children }: ProductCardProps) {
  return (
    <div
      data-testid="product-card"
      className="flex items-center gap-4 rounded-xl border-2 border-[var(--color-stage-border)] bg-[var(--color-stage-surface)] p-3"
    >
      <a
        href={product.url}
        target="_blank"
        rel="noreferrer"
        title={product.title}
        className="flex-shrink-0 rounded-lg focus:outline-none focus-visible:ring-4 focus-visible:ring-[#1E40AF]/40"
      >
        <img
          src={product.image}
          alt={product.title}
          loading="lazy"
          className="h-[8rem] w-[8rem] rounded-lg bg-white object-contain"
        />
      </a>
      {/* The <strong> the LLM wrote is the product name; promote it to its own
          line so the card reads as a title over a description. */}
      <div className="min-w-0 flex-1 text-[1.375rem] leading-snug text-[var(--color-stage-ink-muted)] [&_strong]:mb-1 [&_strong]:block [&_strong]:text-[1.5rem] [&_strong]:font-bold [&_strong]:text-[var(--color-stage-ink)]">
        {children}
      </div>
    </div>
  )
}
