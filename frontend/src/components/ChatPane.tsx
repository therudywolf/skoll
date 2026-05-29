/**
 * ChatPane — the conversation timeline plus the message composer.
 * Issue: phase-1.13.
 *
 * Renders each turn from the `chat` store. Assistant turns are rendered as
 * GitHub-flavoured markdown with syntax-highlighted code blocks
 * (`react-markdown` + `remark-gfm` + `rehype-highlight`). User turns are plain
 * text; error turns use `role="alert"` so failures are announced and assertable.
 *
 * Sending is delegated to the store's `send` action, which currently POSTs to
 * the non-streaming `/api/chat` endpoint. Streaming arrives in phase-1.1.
 */

import { useState, type JSX, type KeyboardEvent } from "react";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import { useChat, type ChatTurn } from "@/stores/chat";

function TurnView({ turn }: { turn: ChatTurn }): JSX.Element {
  if (turn.role === "error") {
    return (
      <div className="chat-turn chat-turn-error" role="alert">
        {turn.content}
      </div>
    );
  }

  if (turn.role === "assistant") {
    return (
      <div className="chat-turn chat-turn-assistant">
        <div className="chat-markdown">
          <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
            {turn.content}
          </Markdown>
        </div>
      </div>
    );
  }

  return <div className="chat-turn chat-turn-user">{turn.content}</div>;
}

export function ChatPane(): JSX.Element {
  const turns = useChat((state) => state.turns);
  const loading = useChat((state) => state.loading);
  const send = useChat((state) => state.send);
  const [input, setInput] = useState("");

  const canSend = !loading && input.trim().length > 0;

  async function handleSend(): Promise<void> {
    if (!canSend) {
      return;
    }
    const text = input;
    setInput("");
    await send(text);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    // Enter sends; Shift+Enter inserts a newline.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  }

  return (
    <section className="chat-pane" aria-label="Chat">
      <div className="chat-timeline" aria-busy={loading}>
        {turns.length === 0 ? (
          <p className="chat-empty">Ask the agent something to get started.</p>
        ) : (
          turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
        )}
        {loading ? (
          <div className="chat-turn chat-turn-pending" aria-label="Assistant is responding">
            Waiting for response…
          </div>
        ) : null}
      </div>

      <div className="chat-composer">
        <textarea
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask the agent…"
          rows={3}
          disabled={loading}
          aria-label="Message"
        />
        <button type="button" onClick={() => void handleSend()} disabled={!canSend}>
          {loading ? "Sending…" : "Send"}
        </button>
      </div>
    </section>
  );
}
