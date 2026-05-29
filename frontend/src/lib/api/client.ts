/**
 * Typed fetch wrapper for the Skoll backend HTTP API.
 *
 * Issue: phase-0.5. Currently only the non-streaming dev chat endpoint
 * (`POST /api/chat`, see backend issue 0.4) is wired. Phase 1.1 moves the
 * real conversation onto the SSE endpoint in `@/lib/sse.ts`.
 *
 * Requests go through Vite's `/api` proxy (see vite.config.ts) to the
 * backend at http://127.0.0.1:8000.
 */

/** A single chat message sent to the backend. */
export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

/** Request body for `POST /api/chat`. */
export interface ChatRequest {
  messages: ChatMessage[];
  /** Model id to use, or `null` to let the backend choose its default. */
  model: string | null;
}

/** Successful (200) response body for `POST /api/chat`. */
export interface ChatResponse {
  content: string;
  model: string;
}

/** Error payload shape returned by the backend on a non-2xx response. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
  };
}

/**
 * Error thrown when the backend responds with a non-2xx status.
 *
 * `code` is the machine-readable code from the backend (or a synthetic
 * `http_<status>` / `malformed_error_response` when the body could not be
 * parsed as the documented error shape).
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as { error?: unknown };
  if (typeof candidate.error !== "object" || candidate.error === null) {
    return false;
  }
  const err = candidate.error as { code?: unknown; message?: unknown };
  return typeof err.code === "string" && typeof err.message === "string";
}

function isChatResponse(value: unknown): value is ChatResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as { content?: unknown; model?: unknown };
  return typeof candidate.content === "string" && typeof candidate.model === "string";
}

async function readErrorBody(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return new ApiError(
      `http_${response.status}`,
      `Request failed with status ${response.status}`,
      response.status,
    );
  }
  if (isApiErrorBody(body)) {
    return new ApiError(body.error.code, body.error.message, response.status);
  }
  return new ApiError(
    "malformed_error_response",
    `Request failed with status ${response.status}`,
    response.status,
  );
}

/**
 * POST a single user message to the non-streaming chat endpoint and return
 * the assistant's reply.
 *
 * @param input  The raw user text.
 * @param model  Model id to use, or `null` (default) to let the backend pick.
 * @throws {ApiError} when the backend responds with a non-2xx status or an
 *   unexpected success body.
 */
export async function postChat(input: string, model: string | null = null): Promise<ChatResponse> {
  const requestBody: ChatRequest = {
    messages: [{ role: "user", content: input }],
    model,
  };

  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(requestBody),
  });

  if (!response.ok) {
    throw await readErrorBody(response);
  }

  const data: unknown = await response.json();
  if (!isChatResponse(data)) {
    throw new ApiError(
      "malformed_response",
      "Backend returned an unexpected response shape",
      response.status,
    );
  }
  return data;
}
