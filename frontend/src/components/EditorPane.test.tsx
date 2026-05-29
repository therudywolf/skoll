import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { EditorPane, languageFromPath } from "@/components/EditorPane";

afterEach(() => {
  cleanup();
});

describe("languageFromPath", () => {
  it("maps known extensions to Monaco language ids", () => {
    expect(languageFromPath("src/App.tsx")).toBe("typescript");
    expect(languageFromPath("main.py")).toBe("python");
    expect(languageFromPath("data.json")).toBe("json");
    expect(languageFromPath("notes.md")).toBe("markdown");
    expect(languageFromPath("C:\\repo\\lib.rs")).toBe("rust");
  });

  it("recognises Dockerfile by name and falls back to plaintext otherwise", () => {
    expect(languageFromPath("Dockerfile")).toBe("dockerfile");
    expect(languageFromPath("LICENSE")).toBe("plaintext");
    expect(languageFromPath("weird.unknownext")).toBe("plaintext");
  });
});

describe("EditorPane", () => {
  it("renders the read-only Monaco editor with the welcome buffer by default", () => {
    render(<EditorPane />);
    const editor = screen.getByTestId("monaco");
    expect(editor).toHaveAttribute("readonly");
    expect((editor as HTMLTextAreaElement).value).toContain("Welcome to Sköll");
    expect(editor).toHaveAttribute("data-language", "markdown");
  });

  it("displays a provided file with an inferred language", () => {
    render(<EditorPane path="hello.py" value="print('hi')" />);
    const editor = screen.getByTestId("monaco");
    expect(editor).toHaveValue("print('hi')");
    expect(editor).toHaveAttribute("data-language", "python");
    expect(screen.getByText("hello.py")).toBeInTheDocument();
  });
});
