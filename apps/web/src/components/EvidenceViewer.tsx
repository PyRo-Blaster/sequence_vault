import { Empty, Tag, Typography } from "antd";
import { useEffect, useRef } from "react";

import type { DocumentBlock } from "../lib/api";
import { segment } from "../lib/codepoints";

export interface Highlight {
  block_id: string;
  start: number;
  end: number;
  mark: "name" | "sequence" | "issue";
}

function location(block: DocumentBlock): string {
  const loc = block.location as Record<string, unknown>;
  if (loc.kind === "text") {
    return loc.line_start === loc.line_end
      ? `第 ${loc.line_start} 行`
      : `第 ${loc.line_start}–${loc.line_end} 行`;
  }
  if (loc.kind === "spreadsheet_cell") return `${loc.worksheet} ${loc.cell}`;
  if (loc.kind === "pdf_region") return `第 ${loc.page} 页`;
  return String(loc.kind);
}

/** Immutable source blocks with code-point highlights; scrolls to the focused block. */
export function EvidenceViewer({
  blocks,
  highlights,
  focus,
}: {
  blocks: DocumentBlock[];
  highlights: Highlight[];
  focus?: string | null;
}) {
  const refs = useRef(new Map<string, HTMLDivElement>());
  useEffect(() => {
    if (focus) refs.current.get(focus)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);
  if (!blocks.length) return <Empty description="没有可显示的证据" />;
  return (
    // Scrollable, so it must be reachable from the keyboard.
    <div className="sv-evidence" tabIndex={0} role="region" aria-label="原文证据内容">
      {blocks.map((block) => {
        const ranges = highlights
          .filter((h) => h.block_id === block.block_id)
          .map((h) => ({ start: h.start, end: h.end, mark: h.mark }));
        return (
          <div
            key={block.block_id}
            ref={(element) => {
              if (element) refs.current.set(block.block_id, element);
            }}
            className={`sv-block${focus === block.block_id ? " sv-block-focus" : ""}`}
            data-block={block.block_id}
          >
            <div className="sv-block-meta">
              <Tag>{block.block_id}</Tag>
              <Typography.Text type="secondary">
                {location(block)} · {block.type}
              </Typography.Text>
            </div>
            <pre className="sv-block-text">
              {segment(block.raw_text, ranges).map((part, i) =>
                part.marks.length ? (
                  <mark key={i} className={part.marks.map((m) => `sv-mark-${m}`).join(" ")}>
                    {part.text}
                  </mark>
                ) : (
                  <span key={i}>{part.text}</span>
                ),
              )}
            </pre>
          </div>
        );
      })}
    </div>
  );
}
