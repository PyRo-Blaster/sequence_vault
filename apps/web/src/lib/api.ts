import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./api-types";

export type Schemas = components["schemas"];
export type Task = Schemas["Task"];
export type CandidateEnvelope = Schemas["CandidateEnvelope"];
export type Candidate = Schemas["CandidateWire"];
export type Issue = Schemas["Issue"];
export type DocumentBlock = Schemas["Block"];
export type Me = Schemas["Me"];
export type Project = Schemas["Project"];
export type CommitResult = Schemas["CommitResult"];
export type RecordSummary = Schemas["RecordSummary"];
export type RecordDetail = Schemas["RecordDetail"];
export type Span = Schemas["Span"];

const DEV_USER_KEY = "sv.devUser";

export function getDevUser(): string | null {
  try {
    return localStorage.getItem(DEV_USER_KEY);
  } catch {
    return null;
  }
}

export function setDevUser(subject: string | null): void {
  try {
    if (subject) localStorage.setItem(DEV_USER_KEY, subject);
    else localStorage.removeItem(DEV_USER_KEY);
  } catch {
    /* storage unavailable: the session simply is not remembered */
  }
}

/** Error envelope from the API: code, message, request_id, details, retryable. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string,
    readonly details?: unknown,
  ) {
    super(message);
  }
}

const headers: Middleware = {
  onRequest({ request }) {
    request.headers.set("X-Requested-With", "sequence-vault");
    const devUser = getDevUser();
    if (devUser) request.headers.set("X-Dev-User", devUser);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(headers);

interface Result<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Return data or throw ApiError with the server's code and message. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok) return data as T;
  const body = (error ?? {}) as {
    code?: string;
    message?: string;
    request_id?: string;
    details?: unknown;
  };
  throw new ApiError(
    response.status,
    body.code ?? `http_${response.status}`,
    body.message ?? response.statusText,
    body.request_id,
    body.details,
  );
}

/** Raw request for binary bodies and downloads, with the same headers. */
export async function rawFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const requestHeaders = new Headers(init.headers);
  requestHeaders.set("X-Requested-With", "sequence-vault");
  const devUser = getDevUser();
  if (devUser) requestHeaders.set("X-Dev-User", devUser);
  const response = await fetch(path, { ...init, headers: requestHeaders });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      body.code ?? `http_${response.status}`,
      body.message ?? response.statusText,
      body.request_id,
    );
  }
  return response;
}

export async function download(path: string): Promise<void> {
  const response = await rawFetch(path);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "download";
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
