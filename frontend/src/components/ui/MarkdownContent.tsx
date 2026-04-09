import { useMemo } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

export function MarkdownContent({
  content,
  className = "",
}: MarkdownContentProps) {
  const html = useMemo(() => {
    const raw = marked.parse(content, { async: false }) as string;
    return DOMPurify.sanitize(raw);
  }, [content]);

  return (
    <div
      className={`prose prose-invert prose-sm max-w-none break-words overflow-hidden ${className}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
