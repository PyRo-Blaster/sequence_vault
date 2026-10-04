import type { CandidateEnvelope } from "../../lib/api";

/** REVIEW issues still waiting for a resolution on the current revision. */
export function unresolved(envelope: CandidateEnvelope): string[] {
  const { candidate, review } = envelope;
  return candidate.issues
    .filter((issue) => issue.severity === "REVIEW" && !review.resolutions[issue.rule_id])
    .map((issue) => issue.rule_id);
}

export function hasBlock(envelope: CandidateEnvelope): boolean {
  return envelope.candidate.issues.some((issue) => issue.severity === "BLOCK");
}

export function canApprove(envelope: CandidateEnvelope): boolean {
  return (
    envelope.candidate.status === "NEEDS_REVIEW" &&
    !hasBlock(envelope) &&
    unresolved(envelope).length === 0 &&
    !!envelope.candidate.name
  );
}

/** Python's str.isspace() set, which QC02 removes; JS \s differs (U+FEFF, U+001C–U+001F, U+0085). */
const WHITESPACE = new Set(
  [
    ...[0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680],
    ...Array.from({ length: 11 }, (_, i) => 0x2000 + i),
    ...[0x2028, 0x2029, 0x202f, 0x205f, 0x3000],
  ].map((code) => String.fromCodePoint(code)),
);

/** Normalize exactly like QC02: drop whitespace, upper-case ASCII letters. */
export function previewNormalize(text: string): string {
  return Array.from(text)
    .filter((c) => !WHITESPACE.has(c))
    .map((c) => (/[a-z]/.test(c) ? c.toUpperCase() : c))
    .join("");
}
