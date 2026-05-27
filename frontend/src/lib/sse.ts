/**
 * SSE client for /api/sessions/{id}/messages.
 *
 * Issue: phase-1.13 (frontend wiring), phase-1.1 (backend side).
 * Events: see contracts/events.yaml.
 *
 * Browsers' native EventSource doesn't support POST bodies; use fetch + ReadableStream.
 */

import type { AgentEvent } from "@/lib/api/types"; // hand-typed alias of generated types

export interface SSEClientOptions {
  sessionId: string;
  content: string;
  attachments?: unknown[];
  onEvent: (event: AgentEvent) => void;
  signal?: AbortSignal;
}

export async function streamAgentResponse(_opts: SSEClientOptions): Promise<void> {
  // TODO(phase-1.13)
  //   fetch(`/api/sessions/${sessionId}/messages`, {
  //     method: 'POST',
  //     headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
  //     body: JSON.stringify({ content, attachments }),
  //     signal,
  //   })
  //   Parse text/event-stream from response.body as ReadableStream<Uint8Array>
  //   For each event: { name, data: JSON.parse(...) } → onEvent
  throw new Error("not implemented (phase-1.13)");
}
