/**
 * Re-exports + hand-typed unions over the generated openapi types.
 *
 * The file `types.gen.ts` is created by `pnpm gen:types`. Don't edit it; edit this file
 * to add ergonomic aliases.
 */

// Once generated, uncomment:
// export type * from "./types.gen";

// Discriminated union of SSE events. Keep in sync with contracts/events.yaml.
export type AgentEvent =
  | { name: "message_start"; data: { message_id: string; role: "assistant" } }
  | { name: "text_delta"; data: { delta: string } }
  | { name: "tool_call_start"; data: { tool_call_id: string; name: string } }
  | { name: "tool_call_args_delta"; data: { tool_call_id: string; args_delta: string } }
  | {
      name: "tool_call_ready";
      data: {
        tool_call_id: string;
        name: string;
        arguments: Record<string, unknown>;
        requires_approval: boolean;
      };
    }
  | {
      name: "tool_call_approved";
      data: { tool_call_id: string; by: "user" | "auto"; edited?: boolean };
    }
  | { name: "tool_call_rejected"; data: { tool_call_id: string; reason?: string } }
  | {
      name: "tool_call_result";
      data: {
        tool_call_id: string;
        status: "completed" | "failed";
        result?: Record<string, unknown>;
        error?: string;
        duration_ms: number;
      };
    }
  | {
      name: "message_end";
      data: { stop_reason: "end_of_turn" | "max_iterations" | "tool_rejection" | "error" };
    }
  | { name: "error"; data: { code: string; message: string; recoverable: boolean } }
  | { name: "ping"; data: Record<string, never> };
