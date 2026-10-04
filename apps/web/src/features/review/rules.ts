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

/** Normalize like QC02 for previews: drop whitespace, upper-case ASCII letters. */
export function previewNormalize(text: string): string {
  return Array.from(text)
    .filter((c) => !/\s/u.test(c))
    .map((c) => (/[a-z]/.test(c) ? c.toUpperCase() : c))
    .join("");
}
