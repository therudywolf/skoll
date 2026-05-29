import type { JSX } from "react";
import { vi } from "vitest";
import "@testing-library/jest-dom/vitest";

/**
 * Monaco does not run under jsdom (it needs a real DOM + web workers), so mock
 * `@monaco-editor/react` for the whole test run. The stub renders a read-only
 * textarea that mirrors the editor's `value`/`readOnly` props, which is enough
 * for component tests to assert that the right buffer is displayed.
 */
vi.mock("@monaco-editor/react", () => {
  interface StubProps {
    value?: string;
    language?: string;
    options?: { readOnly?: boolean };
  }
  const Editor = ({ value, language, options }: StubProps): JSX.Element => (
    <textarea
      data-testid="monaco"
      data-language={language}
      readOnly={options?.readOnly ?? false}
      value={value ?? ""}
      // The stub never changes; supply a no-op to satisfy React's controlled-input warning.
      onChange={() => undefined}
    />
  );
  return { default: Editor };
});
