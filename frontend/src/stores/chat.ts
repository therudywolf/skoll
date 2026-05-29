/**
 * Zustand store for the chat message timeline.
 * Issue: phase-1.13.
 *
 * Holds the ordered list of turns shown in the ChatPane plus the in-flight
 * loading flag, and exposes a `send` action that POSTs to the non-streaming
 * `/api/chat` endpoint (see `@/lib/api/client`). On success the assistant
 * reply is appended; on failure an `error` turn is appended instead.
 *
 * TODO(phase-1.1): replace `send` with the SSE consumer in `@/lib/sse.ts`
 * once the streaming endpoint lands, accumulating `text_delta` events into the
 * trailing assistant turn.
 */

import { create } from "zustand";

import { ApiError, postChat } from "@/lib/api/client";

/** Role of a single rendered turn in the timeline. */
export type ChatRole = "user" | "assistant" | "error";

/** A single rendered turn in the chat timeline. */
export interface ChatTurn {
  /** Stable id for React keys. */
  id: string;
  role: ChatRole;
  content: string;
}

interface ChatState {
  turns: ChatTurn[];
  loading: boolean;
  /** Append a user turn and request the assistant reply for `input`. */
  send: (input: string) => Promise<void>;
  /** Clear the entire timeline (used by tests). */
  reset: () => void;
}

let turnCounter = 0;
function nextId(role: ChatRole): string {
  turnCounter += 1;
  return `${role}-${turnCounter}`;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) {
    return err.message;
  }
  return "Unexpected error contacting the backend.";
}

export const useChat = create<ChatState>((set, get) => ({
  turns: [],
  loading: false,
  send: async (input: string): Promise<void> => {
    const trimmed = input.trim();
    if (trimmed.length === 0 || get().loading) {
      return;
    }

    const userTurn: ChatTurn = { id: nextId("user"), role: "user", content: trimmed };
    set((state) => ({ turns: [...state.turns, userTurn], loading: true }));

    try {
      const result = await postChat(trimmed);
      const assistantTurn: ChatTurn = {
        id: nextId("assistant"),
        role: "assistant",
        content: result.content,
      };
      set((state) => ({ turns: [...state.turns, assistantTurn], loading: false }));
    } catch (err) {
      const errorTurn: ChatTurn = {
        id: nextId("error"),
        role: "error",
        content: errorMessage(err),
      };
      set((state) => ({ turns: [...state.turns, errorTurn], loading: false }));
    }
  },
  reset: (): void => set({ turns: [], loading: false }),
}));
