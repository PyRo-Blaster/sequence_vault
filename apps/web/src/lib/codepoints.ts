/**
 * The API measures text offsets in Unicode code points (offset_unit=unicode_codepoint).
 * JavaScript strings index UTF-16 code units, so characters outside the Basic Multilingual
 * Plane take two units. Always convert before slicing.
 */

/** UTF-16 index of the code point at `offset` (offset may equal the length). */
export function codePointToUtf16(text: string, offset: number): number {
  if (offset < 0) throw new RangeError(`Negative code point offset ${offset}`);
  let units = 0;
  let points = 0;
  while (points < offset) {
    if (units >= text.length) throw new RangeError(`Offset ${offset} is beyond the text`);
    const code = text.codePointAt(units)!;
    units += code > 0xffff ? 2 : 1;
    points += 1;
  }
  return units;
}

/** Code point offset of a UTF-16 index. */
export function utf16ToCodePoint(text: string, index: number): number {
  return Array.from(text.slice(0, index)).length;
}

/** Slice with code point offsets: [start, end). */
export function sliceCodePoints(text: string, start: number, end: number): string {
  return text.slice(codePointToUtf16(text, start), codePointToUtf16(text, end));
}

export function codePointLength(text: string): number {
  return Array.from(text).length;
}

export interface Segment {
  text: string;
  marks: string[];
}

/** Split text into runs carrying the marks of every range that covers them. */
export function segment(
  text: string,
  ranges: { start: number; end: number; mark: string }[],
): Segment[] {
  const points = Array.from(text);
  const marks: string[][] = points.map(() => []);
  for (const range of ranges) {
    for (let i = Math.max(0, range.start); i < Math.min(points.length, range.end); i += 1) {
      marks[i]!.push(range.mark);
    }
  }
  const segments: Segment[] = [];
  points.forEach((character, i) => {
    const current = marks[i]!;
    const last = segments[segments.length - 1];
    if (last && last.marks.join() === current.join()) last.text += character;
    else segments.push({ text: character, marks: [...current] });
  });
  return segments;
}
