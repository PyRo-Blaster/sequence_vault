import { Typography } from "antd";

const STANDARD = new Set("ACDEFGHIKLMNPQRSTVWY");
const EXTENDED = new Set("BZJXUO");

function residueClass(residue: string): string | undefined {
  if (STANDARD.has(residue)) return undefined;
  if (EXTENDED.has(residue)) return "sv-residue-extended";
  return "sv-residue-invalid";
}

/** Fixed-width sequence in blocks of ten with residue positions at the start of each line. */
export function SequenceView({ sequence, perLine = 60 }: { sequence: string; perLine?: number }) {
  if (!sequence) return <Typography.Text type="secondary">（无序列）</Typography.Text>;
  const residues = Array.from(sequence);
  const lines: string[][] = [];
  for (let i = 0; i < residues.length; i += perLine) lines.push(residues.slice(i, i + perLine));
  return (
    <div className="sv-sequence" aria-label="序列">
      {lines.map((line, row) => (
        <div key={row} className="sv-sequence-line">
          <span className="sv-sequence-position">{row * perLine + 1}</span>
          {Array.from({ length: Math.ceil(line.length / 10) }, (_, block) => (
            <span key={block} className="sv-sequence-block">
              {line.slice(block * 10, block * 10 + 10).map((residue, i) => {
                const className = residueClass(residue);
                return className ? (
                  <mark
                    key={i}
                    className={className}
                    title={`U+${residue.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`}
                  >
                    {residue}
                  </mark>
                ) : (
                  residue
                );
              })}
            </span>
          ))}
        </div>
      ))}
      <Typography.Text type="secondary" className="sv-sequence-length">
        长度 {residues.length}
      </Typography.Text>
    </div>
  );
}
