/**
 * EditorPane — a read-only Monaco editor.
 * Issue: phase-1.13.
 *
 * Displays a file's contents with syntax highlighting, inferring the Monaco
 * language id from the file extension. There is no file tree yet (issue 1.14),
 * so this defaults to a welcome buffer. The editor is strictly read-only for
 * now — write/diff editing arrives with the agent edit tools (phase 2,
 * issue 2.8 for the diff editor).
 */

import Editor from "@monaco-editor/react";
import { useMemo, type JSX } from "react";

const WELCOME_FILE = "welcome.md";

const WELCOME_BUFFER = `# Welcome to Sköll

A local-first agentic web IDE for LM Studio.

This pane is a **read-only** Monaco editor. Once the file tree lands
(issue 1.14) you'll be able to open workspace files here with full
syntax highlighting.

- Ask the agent on the right to get started.
- No cloud. No telemetry. Everything runs locally.
`;

/** Map common file extensions to Monaco language ids. */
const EXTENSION_LANGUAGE: Readonly<Record<string, string>> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  json: "json",
  py: "python",
  rs: "rust",
  go: "go",
  java: "java",
  c: "c",
  h: "c",
  cpp: "cpp",
  hpp: "cpp",
  cs: "csharp",
  rb: "ruby",
  php: "php",
  sh: "shell",
  bash: "shell",
  yml: "yaml",
  yaml: "yaml",
  toml: "ini",
  ini: "ini",
  md: "markdown",
  markdown: "markdown",
  html: "html",
  css: "css",
  scss: "scss",
  sql: "sql",
  xml: "xml",
  dockerfile: "dockerfile",
};

/** Infer a Monaco language id from a file path/name; falls back to plaintext. */
export function languageFromPath(path: string): string {
  const name = path.toLowerCase().split(/[\\/]/).pop() ?? "";
  if (name === "dockerfile") {
    return "dockerfile";
  }
  const dot = name.lastIndexOf(".");
  if (dot < 0) {
    return "plaintext";
  }
  const ext = name.slice(dot + 1);
  return EXTENSION_LANGUAGE[ext] ?? "plaintext";
}

export interface EditorPaneProps {
  /** File name/path used to infer the language. Defaults to the welcome buffer. */
  path?: string;
  /** File contents to display. Defaults to the welcome buffer. */
  value?: string;
}

export function EditorPane({ path, value }: EditorPaneProps): JSX.Element {
  const activePath = path ?? WELCOME_FILE;
  const activeValue = value ?? WELCOME_BUFFER;
  const language = useMemo(() => languageFromPath(activePath), [activePath]);

  return (
    <section className="editor-pane" aria-label="Editor">
      <div className="editor-tabbar" aria-label="Open file">
        {activePath}
      </div>
      <div className="editor-host">
        <Editor
          theme="vs-dark"
          path={activePath}
          language={language}
          value={activeValue}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: 13,
            automaticLayout: true,
          }}
        />
      </div>
    </section>
  );
}
