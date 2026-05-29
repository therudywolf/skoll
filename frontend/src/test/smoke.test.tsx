import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { App } from "@/App";
import { useSession } from "@/stores/session";

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
    const { getByRole } = render(<App />);
    expect(getByRole("heading", { name: "Skoll" }).textContent).toBe("Skoll");
  });
});
