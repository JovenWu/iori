/**
 * Convert markdown to a plain-text snippet for one-line previews (history
 * list, thread titles). Not a parser — just enough normalization that raw
 * `**`, `##`, `|` markers don't bleed into the UI.
 */
export function markdownToPlainText(markdown: string): string {
  if (!markdown) return "";

  return (
    markdown
      // Fenced code blocks: keep the code, drop the fences + language tag.
      .replace(/```[^\n]*\n?([\s\S]*?)(?:```|$)/g, "$1")
      // Inline code keeps its content.
      .replace(/`([^`]*)`/g, "$1")
      // Images collapse to their alt text.
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
      // Links collapse to their label.
      .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      // Block-level markers at line start: headings, quotes, lists, tasks.
      .replace(/^\s{0,3}#{1,6}\s+/gm, "")
      .replace(/^\s*>\s?/gm, "")
      .replace(/^\s*[-*+]\s+(\[[ xX]\]\s+)?/gm, "")
      .replace(/^\s*\d+[.)]\s+/gm, "")
      // Table separator rows vanish; remaining pipes read as separators.
      .replace(/^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/gm, "")
      .replace(/\|/g, " ")
      // Emphasis markers unwrap to their text (bold first so `**` isn't eaten
      // by the single-`*` pass).
      .replace(/(\*\*|__)([\s\S]*?)\1/g, "$2")
      .replace(/(\*|_)([^*_]*?)\1/g, "$2")
      .replace(/~~([\s\S]*?)~~/g, "$1")
      // Horizontal rules and stray HTML tags.
      .replace(/^\s*[-*_]{3,}\s*$/gm, "")
      .replace(/<\/?[a-zA-Z][^>]*>/g, " ")
      // One line, single spaces.
      .replace(/\s+/g, " ")
      .trim()
  );
}
