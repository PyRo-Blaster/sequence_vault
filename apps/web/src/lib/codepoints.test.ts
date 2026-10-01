import { codePointToUtf16, segment, sliceCodePoints, utf16ToCodePoint } from "./codepoints";

describe("code point offsets", () => {
  const text = "名称：𝐀MKT"; // 𝐀 (U+1D400) is two UTF-16 units

  it("slices by code points, not UTF-16 units", () => {
    expect(sliceCodePoints(text, 3, 4)).toBe("𝐀");
    expect(sliceCodePoints(text, 4, 7)).toBe("MKT");
    expect(text.slice(4, 7)).not.toBe("MKT");
  });

  it("converts both ways", () => {
    expect(codePointToUtf16(text, 4)).toBe(5);
    expect(utf16ToCodePoint(text, 5)).toBe(4);
    expect(codePointToUtf16(text, 7)).toBe(text.length);
  });

  it("rejects offsets beyond the text", () => {
    expect(() => codePointToUtf16("MKT", 4)).toThrow(RangeError);
  });

  it("segments overlapping marks", () => {
    expect(
      segment("MKTAY", [
        { start: 1, end: 3, mark: "a" },
        { start: 2, end: 4, mark: "b" },
      ]),
    ).toEqual([
      { text: "M", marks: [] },
      { text: "K", marks: ["a"] },
      { text: "T", marks: ["a", "b"] },
      { text: "A", marks: ["b"] },
      { text: "Y", marks: [] },
    ]);
  });
});
