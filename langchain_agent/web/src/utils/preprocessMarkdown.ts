/**
 * Fix common markdown issues in LLM output: <br> tags and literal "\\n"
 * strings become newlines, and runs of blank lines collapse.
 */
export function preprocessMarkdown(content: string): string {
  return content
    .replace(/<br\s*\/?>/gi, '\n')
    // Literal \n, but not an escaped \\n
    .replace(/(?<!\\)\\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
}
