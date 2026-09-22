/**
 * Message - Single chat message display with markdown support.
 */

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { useState, useMemo, Children, isValidElement } from 'react'
import type { ReactNode } from 'react'
import type { Element, RootContent } from 'hast'
import { User, Bot, BookOpen, ChevronDown, Copy, Check } from 'lucide-react'
import type { ChatMessage } from '../../stores/chatStore'
import { ProductCard } from './ProductCard'
import { indexProducts } from './productIndex'
import type { ProductLookup } from './productIndex'
import clsx from 'clsx'

/**
 * Pre-process markdown content to fix common issues from LLM output.
 * - Converts <br> tags to actual newlines
 * - Converts literal \n strings to newlines
 * - Fixes code blocks that use <br> instead of newlines
 * - Handles non-string content (arrays, objects) by converting to string
 */
function preprocessMarkdown(content: string | unknown): string {
  // Handle non-string content (from Gemini content blocks or other formats)
  let stringContent: string
  if (typeof content !== 'string') {
    if (Array.isArray(content)) {
      // If it's an array of content blocks, extract text from each block
      stringContent = content
        .map(block => {
          if (typeof block === 'object' && block !== null && 'text' in block) {
            return (block as { text: string }).text
          }
          return String(block)
        })
        .join('')
    } else {
      stringContent = String(content)
    }
  } else {
    stringContent = content
  }

  return stringContent
    // Convert <br>, <br/>, <br /> tags to newlines
    .replace(/<br\s*\/?>/gi, '\n')
    // Convert literal \n strings to actual newlines (but not \\n which is escaped)
    .replace(/(?<!\\)\\n/g, '\n')
    // Clean up any double newlines that might result
    .replace(/\n{3,}/g, '\n\n')
}

/** Concatenated text of a hast node, however deeply it is nested. */
function nodeText(node: RootContent): string {
  if (node.type === 'text') return node.value
  if (node.type === 'element') return node.children.map(nodeText).join('')
  return ''
}

/**
 * The first bold run inside a node — the product name, when there is one.
 *
 * Read from the hast tree rather than the rendered children so it works the
 * same for a tight list (`li > strong`) and a loose one (`li > p > strong`),
 * and survives any emphasis nested inside the name.
 */
function firstStrongText(node: Element): string {
  for (const child of node.children) {
    if (child.type !== 'element') continue
    if (child.tagName === 'strong') return nodeText(child)
    const nested = firstStrongText(child)
    if (nested) return nested
  }
  return ''
}

/** Does this list item name a product we can illustrate? */
function itemProduct(node: RootContent | undefined, lookup: ProductLookup) {
  if (!node || node.type !== 'element' || node.tagName !== 'li') return undefined
  return lookup(firstStrongText(node))
}

/**
 * Classes for a list wrapper.
 *
 * A list whose items name products becomes a stack of cards, so it drops its
 * markers and indent and lets the cards span the bubble (#144).
 */
function listClasses(
  node: Element | undefined,
  lookup: ProductLookup,
  marker: 'list-disc' | 'list-decimal'
): string {
  const hasCards = node?.children.some((child) => itemProduct(child, lookup))
  return clsx(
    'my-2',
    hasCards ? 'list-none gap-3 pl-0 ml-0' : `${marker} list-inside space-y-1 ml-2`
  )
}

/**
 * A list item's body, prepared for a card.
 *
 * Two fixes: a loose list wraps the item in a `<p>`, which would add its own
 * margin inside the card; and the LLM writes "**Name** — blurb", where the
 * dash dangles once the name becomes its own line.
 */
function cardBody(children: ReactNode): ReactNode {
  let items = Children.toArray(children)

  const only = items.length === 1 ? items[0] : undefined
  if (isValidElement(only) && only.type === 'p') {
    items = Children.toArray((only.props as { children?: ReactNode }).children)
  }

  const strongAt = items.findIndex((item) => isValidElement(item) && item.type === 'strong')
  const afterName = strongAt === -1 ? undefined : items[strongAt + 1]
  if (typeof afterName === 'string') {
    items[strongAt + 1] = afterName.replace(/^\s*[—–-]\s*/, '')
  }

  return items
}

interface MessageProps {
  message: ChatMessage
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === 'user'
  const [citationsOpen, setCitationsOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [showOriginal, setShowOriginal] = useState(false)
  const citationsCount = message.citations?.length || 0

  // Memoize markdown preprocessing to avoid regex operations on every render
  const processedContent = useMemo(() => {
    return preprocessMarkdown(message.content || '...')
  }, [message.content])

  // Citations only arrive with `agent_complete`, so while the answer streams
  // there is nothing to match against. Gating on it keeps the list from
  // snapping into cards on the final frame — it becomes one deliberate
  // reflow, at the same moment the photos used to appear (#144).
  const findProduct = useMemo<ProductLookup>(
    () => (message.isStreaming ? () => undefined : indexProducts(message.citations)),
    [message.citations, message.isStreaming]
  )

  // Copy message content to clipboard
  const handleCopy = async () => {
    if (!message.content) return

    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy text:', err)
    }
  }

  return (
    <div
      className={clsx(
        'flex gap-3 animate-slide-in',
        isUser ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      {/* Avatar */}
      <div
        className={clsx(
          'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
          isUser ? 'bg-blue-600' : 'bg-[var(--color-stage-raised)]'
        )}
        aria-label={isUser ? 'You' : 'Agent'}
      >
        {isUser ? (
          <User className="w-4 h-4 text-white" aria-hidden="true" />
        ) : (
          <Bot className="w-4 h-4 text-[var(--color-stage-ink-muted)]" aria-hidden="true" />
        )}
      </div>

      {/* Message bubble */}
      <div
        className={clsx(
          'chat-message relative group',
          isUser ? 'chat-message-user' : 'chat-message-assistant'
        )}
      >
        {/* Copy button for assistant messages */}
        {!isUser && (
          <button
            type="button"
            onClick={handleCopy}
            className="absolute top-2 right-2 p-1.5 rounded bg-[var(--color-stage-raised)] hover:bg-[var(--color-stage-border)] opacity-0 group-hover:opacity-100 transition-opacity focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            title={copied ? 'Copied!' : 'Copy message'}
            aria-label={copied ? 'Copied to clipboard' : 'Copy message to clipboard'}
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-green-400" aria-hidden="true" />
            ) : (
              <Copy className="w-3.5 h-3.5 text-[var(--color-stage-ink-muted)]" aria-hidden="true" />
            )}
          </button>
        )}

        {isUser ? (
          <div className="flex flex-col gap-1">
            <p className="text-[1.375rem] whitespace-pre-wrap">{message.content}</p>
            {message.status === 'queued' && (
              <span className="text-[1.25rem] text-blue-200/80">Queued</span>
            )}
          </div>
        ) : (
          <div className="markdown-content text-[1.375rem]">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
              components={{
                // Headings
                h1: ({ children }) => (
                  <h1 className="text-[1.75rem] font-bold text-white mt-4 mb-2">
                    {children}
                  </h1>
                ),
                h2: ({ children }) => (
                  <h2 className="text-[length:var(--text-stage-body)] font-bold text-white mt-3 mb-2">
                    {children}
                  </h2>
                ),
                h3: ({ children }) => (
                  <h3 className="text-[1.375rem] font-semibold text-[var(--color-stage-ink)] mt-2 mb-1">
                    {children}
                  </h3>
                ),
                h4: ({ children }) => (
                  <h4 className="text-[1.375rem] font-semibold text-[var(--color-stage-ink-muted)] mt-2 mb-1">
                    {children}
                  </h4>
                ),
                h5: ({ children }) => (
                  <h5 className="text-[1.25rem] font-semibold text-[var(--color-stage-ink-muted)] mt-2 mb-1">
                    {children}
                  </h5>
                ),
                h6: ({ children }) => (
                  <h6 className="text-[1.25rem] font-semibold text-[var(--color-stage-ink-soft)] mt-2 mb-1">
                    {children}
                  </h6>
                ),
                // Paragraphs
                p: ({ children }) => (
                  <p className="mb-3 leading-relaxed">
                    {children}
                  </p>
                ),
                // Code blocks
                pre: ({ children }) => (
                  <pre className="bg-[var(--color-stage-surface)] rounded-lg p-3 overflow-x-auto text-[1.25rem] my-3 border border-[var(--color-stage-border-soft)]">
                    {children}
                  </pre>
                ),
                code: ({ className, children, ...props }) => {
                  const isInline = !className
                  return isInline ? (
                    <code className="bg-[var(--color-stage-raised)] px-1.5 py-0.5 rounded text-[1.25rem] text-[var(--color-stage-ink)]" {...props}>
                      {children}
                    </code>
                  ) : (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  )
                },
                // Links
                a: ({ children, href }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800 rounded"
                  >
                    {children}
                  </a>
                ),
                // Lists
                ul: ({ children, node }) => (
                  <ul className={listClasses(node, findProduct, 'list-disc')}>
                    {children}
                  </ul>
                ),
                ol: ({ children, node }) => (
                  <ol className={listClasses(node, findProduct, 'list-decimal')}>
                    {children}
                  </ol>
                ),
                li: ({ children, node }) => {
                  const product = itemProduct(node, findProduct)
                  if (!product) {
                    return <li className="text-[var(--color-stage-ink)]">{children}</li>
                  }
                  return (
                    <li className="list-none pl-0">
                      <ProductCard product={product}>{cardBody(children)}</ProductCard>
                    </li>
                  )
                },
                // Tables
                table: ({ children }) => (
                  <div className="overflow-x-auto my-3">
                    <table className="w-full border-collapse text-[1.25rem]">
                      {children}
                    </table>
                  </div>
                ),
                thead: ({ children }) => (
                  <thead className="bg-[var(--color-stage-raised)] border border-[var(--color-stage-border)]">
                    {children}
                  </thead>
                ),
                tbody: ({ children }) => (
                  <tbody className="border border-[var(--color-stage-border)]">
                    {children}
                  </tbody>
                ),
                tr: ({ children }) => (
                  <tr className="border-b border-[var(--color-stage-border)] hover:bg-[var(--color-stage-raised)]/50 transition-colors">
                    {children}
                  </tr>
                ),
                th: ({ children }) => (
                  <th className="px-3 py-2 text-left font-semibold text-[var(--color-stage-ink-muted)] border-r border-[var(--color-stage-border)] last:border-r-0 bg-[var(--color-stage-raised)]">
                    {children}
                  </th>
                ),
                td: ({ children }) => (
                  <td className="px-3 py-2 text-[var(--color-stage-ink-muted)] border-r border-[var(--color-stage-border)] last:border-r-0">
                    {children}
                  </td>
                ),
                // Blockquotes
                blockquote: ({ children }) => (
                  <blockquote className="border-l-4 border-[var(--color-stage-border)] pl-4 italic text-[var(--color-stage-ink-muted)] my-3">
                    {children}
                  </blockquote>
                ),
                // Horizontal rule
                hr: () => (
                  <hr className="my-4 border-t border-[var(--color-stage-border)]" />
                ),
              }}
            >
              {processedContent}
            </ReactMarkdown>
          </div>
        )}

        {message.corrected && !isUser && (
          <div className="mt-3 flex flex-col gap-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                title={
                  message.originalFaithfulness !== undefined && message.correctedFaithfulness !== undefined
                    ? `Faithfulness improved ${Math.round(message.originalFaithfulness * 100)}% → ${Math.round(message.correctedFaithfulness * 100)}%`
                    : 'Response corrected by AI judge'
                }
                className="text-[1.25rem] text-[#92400E] border border-[#92400E]/40 rounded px-1.5 py-0.5 cursor-default select-none"
              >
                AI-corrected
              </span>
              {message.originalContent && (
                <button
                  type="button"
                  onClick={() => setShowOriginal((prev) => !prev)}
                  className="text-[1.25rem] text-[var(--color-stage-ink-soft)] hover:text-[var(--color-stage-ink-muted)] underline focus:outline-none"
                >
                  {showOriginal ? 'Hide original' : 'Show original'}
                </button>
              )}
            </div>
            {showOriginal && message.originalContent && (
              <div className="pl-3 border-l-2 border-[#92400E]/40">
                <p className="text-[1.25rem] text-[#92400E] font-semibold mb-1">Original (before correction):</p>
                <p className="text-[1.25rem] text-[var(--color-stage-ink-soft)] whitespace-pre-wrap">{message.originalContent}</p>
              </div>
            )}
          </div>
        )}

        {citationsCount > 0 && (
          /* Citations are supporting material, not part of the answer, so this
             reads as a quiet footer rule and a count rather than a call to
             action. Previously bare blue link text at 1.25rem on a light
             bubble — low contrast and easy to miss projected. */
          <div className="mt-4 border-t-2 border-[var(--color-stage-border)] pt-3">
            <button
              type="button"
              onClick={() => setCitationsOpen((prev) => !prev)}
              aria-expanded={citationsOpen}
              className="flex items-center gap-2.5 rounded-lg px-1 py-1 text-[1.25rem] font-semibold text-[var(--color-stage-ink-muted)] hover:text-[var(--color-stage-ink)] focus:outline-none focus:ring-4 focus:ring-[#1E40AF]/30"
            >
              <BookOpen
                className="h-5 w-5 text-[var(--color-stage-ink-soft)]"
                strokeWidth={2.5}
                aria-hidden="true"
              />
              <span>
                {citationsCount} {citationsCount === 1 ? 'source' : 'sources'}
              </span>
              <ChevronDown
                className={`h-5 w-5 text-[var(--color-stage-ink-soft)] transition-transform ${
                  citationsOpen ? 'rotate-180' : ''
                }`}
                strokeWidth={2.5}
                aria-hidden="true"
              />
            </button>
            {citationsOpen && (
              <ol className="mt-3 flex flex-col gap-2">
                {message.citations?.map((cite, i) => (
                  <li key={cite.url} className="flex gap-3 text-[1.25rem] leading-snug">
                    <span className="min-w-[1.7rem] font-mono font-semibold text-[var(--color-stage-ink-soft)]">
                      {i + 1}.
                    </span>
                    <a
                      href={cite.url}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded text-[#1E40AF] underline decoration-2 underline-offset-2 hover:no-underline focus:outline-none focus:ring-2 focus:ring-[#1E40AF]"
                      title={cite.url}
                    >
                      {cite.label}
                    </a>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}

        {/* Streaming indicator */}
        {message.isStreaming && (
          <span className="inline-block w-2 h-4 bg-gray-400 animate-pulse ml-0.5" aria-label="Generating response" aria-hidden="false" />
        )}
      </div>
    </div>
  )
}
