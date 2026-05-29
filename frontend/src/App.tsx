/**
 * Top-level layout.
 *
 * Phase 0.5: a single textarea + send button + response panel.
 * Phase 1.13: two-pane layout — read-only Monaco editor on the left, chat on
 *   the right. The file tree (issue 1.14) will become a third column.
 * Phase 3.8: swap the static split for react-mosaic for persistent panes.
 */

import type { JSX } from "react";

import { ChatPane } from "@/components/ChatPane";
import { EditorPane } from "@/components/EditorPane";

export function App(): JSX.Element {
  return (
    <div className="app-root">
      <header className="app-header">
        <h1>Skoll</h1>
        <span className="subtitle">local-first agentic IDE — work in progress</span>
      </header>

      <main className="app-main">
        <EditorPane />
        <ChatPane />
      </main>
    </div>
  );
}
