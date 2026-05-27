/**
 * Zustand store for the active agent session.
 * Issue: phase-1.13.
 *
 * Holds: current session id, message timeline, in-flight tool calls awaiting approval.
 */

import { create } from "zustand";

interface SessionState {
  sessionId: string | null;
  // TODO(phase-1.13): messages, pendingToolCalls, etc.
  setSessionId: (id: string | null) => void;
}

export const useSession = create<SessionState>((set) => ({
  sessionId: null,
  setSessionId: (id) => set({ sessionId: id }),
}));
