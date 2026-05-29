import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "@/App";
import type { ChatRequest, ChatResponse } from "@/lib/api/client";
import { useChat } from "@/stores/chat";
import { useSession } from "@/stores/session";

beforeEach(() => {
  // The chat store is a module-level singleton; reset it so turns from one
  // test never leak into the next.
  useChat.getState().reset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** The chat composer textarea, addressed by its accessible name so it is not
 *  confused with the (read-only) Monaco editor textarea. */
function messageBox(): HTMLElement {
  return screen.getByRole("textbox", { name: "Message" });
}

describe("session store", () => {
  it("starts with no session and updates on set", () => {
    useSession.setState({ sessionId: null });
    expect(useSession.getState().sessionId).toBeNull();

    useSession.getState().setSessionId("abc-123");
    expect(useSession.getState().sessionId).toBe("abc-123");
  });
});

describe("App", () => {
  it("renders the Skoll heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Skoll" }).textContent).toBe("Skoll");
  });

  it("renders both the editor and chat panes", () => {
    render(<App />);
    expect(screen.getByRole("region", { name: "Editor" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Chat" })).toBeInTheDocument();
  });

  it("disables Send until the textarea has non-whitespace input", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "Send" });
    expect(button).toBeDisabled();

    fireEvent.change(messageBox(), { target: { value: "   " } });
    expect(button).toBeDisabled();

    fireEvent.change(messageBox(), { target: { value: "hello" } });
    expect(button).toBeEnabled();
  });

  it("sends to /api/chat and renders the assistant content", async () => {
    const responseBody: ChatResponse = { content: "Hello from the model!", model: "test-model" };
    const fetchMock = vi.fn(
      (_input: RequestInfo | URL, _init?: RequestInit): Promise<Response> =>
        Promise.resolve(
          new Response(JSON.stringify(responseBody), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.change(messageBox(), { target: { value: "hi there" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText("Hello from the model!")).toBeInTheDocument();
    });

    // Verify the request matched the documented /api/chat contract exactly.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chat");
    expect(init?.method).toBe("POST");
    const sentBody = JSON.parse(String(init?.body)) as ChatRequest;
    expect(sentBody).toEqual({
      messages: [{ role: "user", content: "hi there" }],
      model: null,
    });
  });

  it("renders the backend error message on a non-2xx response", async () => {
    const fetchMock = vi.fn(
      (_input: RequestInfo | URL, _init?: RequestInit): Promise<Response> =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              error: { code: "lm_studio_unreachable", message: "LM Studio is down" },
            }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          ),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.change(messageBox(), { target: { value: "hi there" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toBe("LM Studio is down");
    });
  });
});
