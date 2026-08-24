/**
 * Message - Single chat message display with markdown support.
 */

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { useState, useMemo } from 'react'
import { User, Bot, ChevronDown, ChevronUp, Copy, Check } from 'lucide-react'
import type { ChatMessage } from '../../stores/chatStore'
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
          isUser ? 'bg-blue-600' : 'bg-gray-700'
        )}
        aria-label={isUser ? 'You' : 'Agent'}
      >
        {isUser ? (
          <User className="w-4 h-4 text-white" aria-hidden="true" />
        ) : (
          <Bot className="w-4 h-4 text-gray-300" aria-hidden="true" />
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
            className="absolute top-2 right-2 p-1.5 rounded bg-gray-700 hover:bg-gray-600 opacity-0 group-hover:opacity-100 transition-opacity focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            title={copied ? 'Copied!' : 'Copy message'}
            aria-label={copied ? 'Copied to clipboard' : 'Copy message to clipboard'}
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-green-400" aria-hidden="true" />
            ) : (
              <Copy className="w-3.5 h-3.5 text-gray-300" aria-hidden="true" />
            )}
          </button>
        )}

        {isUser ? (
          <div className="flex flex-col gap-1">
            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
            {message.status === 'queued' && (
              <span className="text-xs text-blue-200/80">Queued</span>
            )}
          </div>
        ) : (
          <div className="markdown-content text-sm">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
              components={{
                // Headings
                h1: ({ children }) => (
                  <h1 className="text-lg font-bold text-white mt-4 mb-2">
                    {children}
                  </h1>
                ),
                h2: ({ children }) => (
                  <h2 className="text-base font-bold text-white mt-3 mb-2">
                    {children}
                  </h2>
                ),
                h3: ({ children }) => (
                  <h3 className="text-sm font-semibold text-gray-100 mt-2 mb-1">
                    {children}
                  </h3>
                ),
                h4: ({ children }) => (
                  <h4 className="text-sm font-semibold text-gray-200 mt-2 mb-1">
                    {children}
                  </h4>
                ),
                h5: ({ children }) => (
                  <h5 className="text-xs font-semibold text-gray-300 mt-2 mb-1">
                    {children}
                  </h5>
                ),
                h6: ({ children }) => (
                  <h6 className="text-xs font-semibold text-gray-400 mt-2 mb-1">
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
                  <pre className="bg-gray-900 rounded-lg p-3 overflow-x-auto text-xs my-3 border border-gray-800">
                    {children}
                  </pre>
                ),
                code: ({ className, children, ...props }) => {
                  const isInline = !className
                  return isInline ? (
                    <code className="bg-gray-700 px-1.5 py-0.5 rounded text-xs text-gray-100" {...props}>
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
                ul: ({ children }) => (
                  <ul className="list-disc list-inside my-2 space-y-1 ml-2">
                    {children}
                  </ul>
                ),
                ol: ({ children }) => (
                  <ol className="list-decimal list-inside my-2 space-y-1 ml-2">
                    {children}
                  </ol>
                ),
                li: ({ children }) => (
                  <li className="text-gray-100">
                    {children}
                  </li>
                ),
                // Tables
                table: ({ children }) => (
                  <div className="overflow-x-auto my-3">
                    <table className="w-full border-collapse text-xs">
                      {children}
                    </table>
                  </div>
                ),
                thead: ({ children }) => (
                  <thead className="bg-gray-800 border border-gray-700">
                    {children}
                  </thead>
                ),
                tbody: ({ children }) => (
                  <tbody className="border border-gray-700">
                    {children}
                  </tbody>
                ),
                tr: ({ children }) => (
                  <tr className="border-b border-gray-700 hover:bg-gray-800/50 transition-colors">
                    {children}
                  </tr>
                ),
                th: ({ children }) => (
                  <th className="px-3 py-2 text-left font-semibold text-gray-200 border-r border-gray-700 last:border-r-0 bg-gray-800">
                    {children}
                  </th>
                ),
                td: ({ children }) => (
                  <td className="px-3 py-2 text-gray-300 border-r border-gray-700 last:border-r-0">
                    {children}
                  </td>
                ),
                // Blockquotes
                blockquote: ({ children }) => (
                  <blockquote className="border-l-4 border-gray-600 pl-4 italic text-gray-300 my-3">
                    {children}
                  </blockquote>
                ),
                // Horizontal rule
                hr: () => (
                  <hr className="my-4 border-t border-gray-700" />
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
                className="text-xs text-amber-400 border border-amber-400/30 rounded px-1.5 py-0.5 cursor-default select-none"
              >
                AI-corrected
              </span>
              {message.originalContent && (
                <button
                  type="button"
                  onClick={() => setShowOriginal((prev) => !prev)}
                  className="text-xs text-gray-400 hover:text-gray-300 underline focus:outline-none"
                >
                  {showOriginal ? 'Hide original' : 'Show original'}
                </button>
              )}
            </div>
            {showOriginal && message.originalContent && (
              <div className="pl-3 border-l-2 border-amber-400/30">
                <p className="text-xs text-amber-400/70 font-semibold mb-1">Original (before correction):</p>
                <p className="text-xs text-gray-400 whitespace-pre-wrap">{message.originalContent}</p>
              </div>
            )}
          </div>
        )}

        {citationsCount > 0 && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setCitationsOpen((prev) => !prev)}
              className="flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200"
            >
              <span>Sources ({citationsCount})</span>
              {citationsOpen ? (
                <ChevronUp className="w-3 h-3" />
              ) : (
                <ChevronDown className="w-3 h-3" />
              )}
            </button>
            {citationsOpen && (
              <ul className="mt-1 space-y-1 text-xs text-blue-200 list-disc list-inside">
                {message.citations?.map((cite) => (
                  <li key={cite.url}>
                    <a
                      href={cite.url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline hover:text-blue-100"
                      title={cite.url}
                    >
                      {cite.label}
                    </a>
                  </li>
                ))}
              </ul>
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
