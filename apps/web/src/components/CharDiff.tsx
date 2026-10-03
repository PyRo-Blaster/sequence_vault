import { diffChars } from "diff";

/** Character-level difference between the current and the proposed sequence. */
export function CharDiff({ before, after }: { before: string; after: string }) {
  const parts = diffChars(before, after);
  const changed = parts.some((part) => part.added || part.removed);
  if (!changed) return <span className="sv-diff-none">（无变化）</span>;
  return (
    <pre className="sv-diff" aria-label="字符差异">
      {parts.map((part, i) =>
        part.added ? (
          <ins key={i}>{part.value}</ins>
        ) : part.removed ? (
          <del key={i}>{part.value}</del>
        ) : (
          <span key={i}>{part.value}</span>
        ),
      )}
    </pre>
  );
}
