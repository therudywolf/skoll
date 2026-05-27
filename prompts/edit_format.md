# SEARCH/REPLACE edit format

> The `apply_diff` tool uses this format. It's adapted from Aider's edit format because it's the most reliable across local models.

## How to use

Each block specifies:
- `search`: the exact existing text in the file
- `replace`: the new text

Rules:
- `search` must match the file content **byte-for-byte** including indentation, trailing whitespace, and newlines.
- Whitespace-only matches are rejected (would be ambiguous).
- If `search` appears multiple times, the call fails with `search_ambiguous`. Add more context lines to disambiguate.
- If `search` is not found, the call fails with `search_not_found`. Use `read_file` to verify the current state.
- To delete code, set `replace` to an empty string.
- To insert code, set `search` to a unique nearby line and `replace` to that same line followed by the new code.

## Example: rename a function

File before:

```python
def fetch(url):
    return requests.get(url).json()

def main():
    data = fetch("https://api.example.com")
```

Tool call:

```json
{
  "name": "apply_diff",
  "arguments": {
    "path": "main.py",
    "reason": "rename fetch -> fetch_json for clarity",
    "blocks": [
      {
        "search": "def fetch(url):\n    return requests.get(url).json()\n",
        "replace": "def fetch_json(url):\n    return requests.get(url).json()\n"
      },
      {
        "search": "    data = fetch(\"https://api.example.com\")",
        "replace": "    data = fetch_json(\"https://api.example.com\")"
      }
    ]
  }
}
```

## Example: insert a line

```json
{
  "blocks": [
    {
      "search": "from fastapi import FastAPI\n",
      "replace": "from fastapi import FastAPI\nfrom skoll.config import settings\n"
    }
  ]
}
```

## Anti-patterns

- ❌ Putting the entire file in `search` to "be safe" — large `search` blocks are fragile to whitespace changes.
- ❌ Using `...` or `// existing code` placeholders inside `search` — they're not interpreted.
- ❌ Reformatting unrelated code in the `replace` — keep diffs minimal.
- ❌ Concatenating unrelated changes into one block — use multiple blocks instead.

## Tips for the model

- Read the file with `read_file` immediately before generating the diff. Stale assumptions about file contents cause `search_not_found`.
- For tiny changes (one line), include 1-2 lines of surrounding context in `search` to make it unique.
- For larger changes, split into multiple blocks rather than one giant block — easier to recover if one block fails.
