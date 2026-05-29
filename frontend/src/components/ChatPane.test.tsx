import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ChatPane } from "@/components/ChatPane";
import type { ChatResponse } from "@/lib/api/client";
import { useChat } from "@/stores/chat";

beforeEach(() => {
  useChat.getState().reset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ChatPane", () => {
  it("renders an empty-state hint before any turns", () => {
    render(<ChatPane />);
    expect(screen.getByText("Ask the agent something to get started.")).toBeInTheDocument();
  });

  it("renders a user turn and a markdown-rendered assistant turn", () => {
    useChat.setState({
      turns: [
        { id: "user-1", role: "user", content: "show me a heading and code" },
        {
          id: "assistant-1",
          role: "assistant",
          content: "# Title\n\nSome **bold** text and `inline` code.\n\n```ts\nconst x = 1;\n```",
        },
      ],
      loading: false,
    });
    render(<ChatPane />);

    // User turn is plain text.
    expect(screen.getByText("show me a heading and code")).toBeInTheDocument();

    // Assistant markdown becomes real DOM: a heading, a <strong>, and a code block.
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    // rehype-highlight wraps the fenced block in <pre><code class="hljs ...">
    // and splits it into token <span>s, so assert on the highlighted keyword.
    const keyword = screen.getByText("const");
    expect(keyword.tagName).toBe("SPAN");
    expect(keyword).toHaveClass("hljs-keyword");
    expect(keyword.closest("pre")).not.toBeNull();
  });

  it("appends user + assistant turns through the store on Send", async () => {
    const responseBody: ChatResponse = { content: "**done**", model: "test-model" };
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(responseBody), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );

    render(<ChatPane />);
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "hi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText("done").tagName).toBe("STRONG");
    });
    expect(screen.getByText("hi")).toBeInTheDocument();
  });

  it("renders a failed request as an alert turn", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ error: { code: "boom", message: "backend exploded" } }),
            { status: 500, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );

    render(<ChatPane />);
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "hi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toBe("backend exploded");
    });
  });
});
