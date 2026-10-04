/** Raised when the page is not a secure context, where browsers hide `crypto.subtle`. */
export class InsecureContextError extends Error {
  readonly code = "insecure_context";
  constructor() {
    super("Uploads need HTTPS: this browser only computes SHA-256 on secure pages.");
  }
}

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  // Browsers expose crypto.subtle only over HTTPS or on localhost.
  const subtle = globalThis.crypto?.subtle as SubtleCrypto | undefined;
  if (!subtle) throw new InsecureContextError();
  const digest = await subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}
