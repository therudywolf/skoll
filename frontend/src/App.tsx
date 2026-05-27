/**
 * Top-level layout.
 *
 * Phase 0.5: just a textarea + send button + response panel.
 * Phase 1.13: replace with Monaco + ChatPane + FileTree.
 * Phase 3.8: add react-mosaic for persistent pane layout.
 */

import { useState } from "react";

export function App(): JSX.Element {
  const [input, setInput] = useState("");
  const [response, setResponse] = useState("");

  // TODO(phase-0.5): wire to POST /api/chat
  // TODO(phase-1.1): switch to SSE consumer (see @/lib/sse.ts)
  async function handleSend(): Promise<void> {
    setResponse("(not implemented — see phase-0.5 issue)");
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
        />
        <button type="button" onClick={() => void handleSend()}>
          Send
        </button>
        <pre className="chat-output">{response}</pre>
      </main>
    </div>
  );
}
