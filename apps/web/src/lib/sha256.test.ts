import { afterEach, describe, expect, it, vi } from "vitest";
import { errorText } from "./i18n";
import { sha256Hex } from "./sha256";

describe("sha256Hex", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("hashes bytes", async () => {
    const bytes = new TextEncoder().encode("abc").buffer as ArrayBuffer;
    expect(await sha256Hex(bytes)).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("explains that uploads need HTTPS when crypto.subtle is missing", async () => {
    vi.stubGlobal("crypto", {});
    const error = await sha256Hex(new ArrayBuffer(1)).catch((e: unknown) => e);
    expect(errorText(error)).toContain("HTTPS");
  });
});
