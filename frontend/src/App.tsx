/**
 * Top-level layout.
 *
 * Phase 0.5: just a textarea + send button + response panel.
 * Phase 1.13: replace with Monaco + ChatPane + FileTree.
 * Phase 3.8: add react-mosaic for persistent pane layout.
 */

import { useState } from "react";

import { ApiError, postChat } from "@/lib/api/client";

export function App(): JSX.Element {
  const [input, setInput] = useState("");
  const [response, setResponse] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const canSend = !loading && input.trim().length > 0;

  // TODO(phase-1.1): switch to SSE consumer (see @/lib/sse.ts)
  async function handleSend(): Promise<void> {
    if (!canSend) {
      return;
    }
    setLoading(true);
    setError("");
    setResponse("");
    try {
      const result = await postChat(input);
      setResponse(result.content);
    } catch (err) {
      const message =
        err instanceof ApiError || err instanceof Error
          ? err.message
          : "Unexpected error contacting the backend.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-root">
      <header className="app-header">
        <h1>Skoll</h1>
        <span className="subtitle">local-first agentic IDE — work in progress</span>
      </header>

      <main className="app-main">
        <textarea
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask the agent…"
          rows={6}
          disabled={loading}
        />
        <button type="button" onClick={() => void handleSend()} disabled={!canSend}>
          {loading ? "Sending…" : "Send"}
        </button>
        {error ? (
          <pre className="chat-error" role="alert">
            {error}
          </pre>
        ) : (
          <pre className="chat-output" aria-busy={loading}>
            {loading ? "Waiting for response…" : response}
          </pre>
        )}
      </main>
    </div>
  );
}
