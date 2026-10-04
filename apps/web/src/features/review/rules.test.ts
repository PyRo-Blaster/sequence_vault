import type { CandidateEnvelope } from "../../lib/api";
import { canApprove, previewNormalize, unresolved } from "./rules";

function envelope(
  overrides: Partial<CandidateEnvelope["candidate"]> = {},
  resolutions: Record<string, string> = {},
): CandidateEnvelope {
  return {
    candidate: {
      schema_version: "1.0",
      candidate_id: "c1",
      run_id: "r1",
      revision: 1,
      name: { value: "A1", source: "fasta_header", evidence: { block_id: "h0", start: 0, end: 2 } },
      extracted_names: [],
      sequence_spans: [],
      raw_text: "MKT",
      normalized_sequence: "MKT",
      molecule_type: "protein",
      completeness: "complete",
      status: "NEEDS_REVIEW",
      origin: "extracted",
      transformation_log: [],
      issues: [],
      qc_version: "1.0",
      ...overrides,
    },
    review: { resolutions, approved_revision: null, typed_sequence: null, allowed_resolutions: {} },
  };
}

const issue = (rule_id: string, severity: "INFO" | "REVIEW" | "BLOCK") => ({
  rule_id,
  severity,
  message: "m",
  evidence: [],
});

describe("review rules", () => {
  it("requires every REVIEW issue to be resolved and no BLOCK issue", () => {
    expect(canApprove(envelope())).toBe(true);
    const review = envelope({ issues: [issue("QC04", "REVIEW"), issue("QC02", "INFO")] });
    expect(unresolved(review)).toEqual(["QC04"]);
    expect(canApprove(review)).toBe(false);
    expect(
      canApprove(
        envelope({ issues: [issue("QC04", "REVIEW")] }, { QC04: "confirm_residue_semantics" }),
      ),
    ).toBe(true);
    expect(canApprove(envelope({ issues: [issue("QC05", "BLOCK")] }))).toBe(false);
    expect(canApprove(envelope({ name: null }))).toBe(false);
  });

  it("normalizes previews like QC02", () => {
    expect(previewNormalize("mk t\nAß")).toBe("MKTAß");
  });
});
