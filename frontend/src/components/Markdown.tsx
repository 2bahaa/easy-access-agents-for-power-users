import type { ReactNode } from "react";

/**
 * Minimal, safe Markdown renderer for chat replies: headings, paragraphs, lists,
 * fenced code, blockquotes, inline code, bold, italic and http(s) links.
 * It builds React elements only (no innerHTML), so model output cannot inject markup.
 */

type Block =
  | { type: "code"; lang: string; text: string }
  | { type: "heading"; level: number; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "quote"; text: string }
  | { type: "paragraph"; text: string };

function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    const fence = line.match(/^\s*```(\S*)/);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i]!)) body.push(lines[i++]!);
      i++; // closing fence (or end of input while streaming)
      blocks.push({ type: "code", lang: fence[1] ?? "", text: body.join("\n") });
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1]!.length, text: heading[2]! });
      i++;
      continue;
    }
    const listMatch = line.match(/^\s*([-*+]|\d+[.)])\s+/);
    if (listMatch) {
      const ordered = /\d/.test(listMatch[1]!);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i]!)) {
        items.push(lines[i]!.replace(/^\s*([-*+]|\d+[.)])\s+/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i]!)) body.push(lines[i++]!.replace(/^\s*>\s?/, ""));
      blocks.push({ type: "quote", text: body.join(" ") });
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const body: string[] = [];
    while (
      i < lines.length &&
      lines[i]!.trim() &&
      !/^\s*(```|#{1,4}\s|[-*+]\s|\d+[.)]\s|>)/.test(lines[i]!)
    ) {
      body.push(lines[i++]!);
    }
    blocks.push({ type: "paragraph", text: body.join("\n") });
  }
  return blocks;
}

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;

function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(INLINE)) {
    const token = match[0];
    const start = match.index ?? 0;
    if (start > last) out.push(text.slice(last, start));
    if (token.startsWith("`")) {
      out.push(
        <code key={key++} className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[0.85em] ring-1 ring-line">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      out.push(<strong key={key++} className="font-semibold">{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*")) {
      out.push(<em key={key++}>{token.slice(1, -1)}</em>);
    } else {
      const [, label, href] = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/) ?? [];
      out.push(
        <a key={key++} href={href} target="_blank" rel="noreferrer noopener" className="font-medium text-brand-600 underline underline-offset-2 dark:text-brand-400">
          {label}
        </a>,
      );
    }
    last = start + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function withBreaks(text: string): ReactNode[] {
  return text.split("\n").flatMap((line, i) => (i === 0 ? renderInline(line) : [<br key={`br${i}`} />, ...renderInline(line)]));
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={className ?? "space-y-3 text-[14.5px] leading-relaxed"}>
      {parseBlocks(text).map((block, i) => {
        switch (block.type) {
          case "code":
            return (
              <pre key={i} className="scrollbar-thin overflow-x-auto rounded-xl bg-[#0f1220] p-3.5 font-mono text-[12.5px] leading-relaxed text-slate-100">
                {block.lang && <span className="mb-2 block text-[10px] tracking-wider text-slate-400 uppercase">{block.lang}</span>}
                <code>{block.text}</code>
              </pre>
            );
          case "heading": {
            const sizes = ["text-lg", "text-base", "text-[15px]", "text-sm"];
            return (
              <p key={i} role="heading" aria-level={block.level} className={`${sizes[block.level - 1]} font-semibold tracking-tight`}>
                {renderInline(block.text)}
              </p>
            );
          }
          case "list": {
            const Tag = block.ordered ? "ol" : "ul";
            return (
              <Tag key={i} className={`space-y-1 pl-5 ${block.ordered ? "list-decimal" : "list-disc"} marker:text-subtle`}>
                {block.items.map((item, j) => (
                  <li key={j}>{renderInline(item)}</li>
                ))}
              </Tag>
            );
          }
          case "quote":
            return (
              <blockquote key={i} className="border-l-2 border-brand-500/50 pl-3 text-muted">
                {renderInline(block.text)}
              </blockquote>
            );
          default:
            return <p key={i}>{withBreaks(block.text)}</p>;
        }
      })}
    </div>
  );
}

