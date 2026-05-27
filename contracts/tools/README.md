# contracts/tools/

Each file is a JSON Schema describing one agent tool.

## File format

Every tool file has the same top-level shape:

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "name": "snake_case_tool_name",        // matches LM Studio tool name normalization
  "description": "...",                  // shown to the LLM
  "phase": "1" | "2" | "3",              // which roadmap phase introduces this tool
  "kind": "read" | "write" | "shell" | "url_fetch" | "vision" | "vcs",
  "requires_approval": true | false,     // human-in-the-loop gate
  "auto_approve_default": true | false,  // can session settings opt in?
  "path_args": ["path"],                  // arg names that are filesystem paths (for validation)
  "parameters": {                         // ← this is what LM Studio receives as `function.parameters`
    "type": "object",
    "properties": { ... },
    "required": [...]
  },
  "result_schema": {                      // shape of the result the tool returns
    "type": "object",
    "properties": { ... }
  }
}
```

Backend reads all files in this directory at startup and registers tools. Frontend reads the same files to render `ToolCallCard` with proper arg editors.

## Naming convention

`snake_case` only. LM Studio 0.3.6+ normalizes tool names anyway, but consistency wins.
