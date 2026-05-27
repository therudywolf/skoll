#!/usr/bin/env python3
"""
Sandbox control entrypoint.

Receives JSON commands over stdin from the backend, runs them under bash,
streams stdout/stderr back as JSON lines.

Protocol (one JSON object per line, bidirectional):

REQUEST:
  {"id": "<uuid>", "action": "run_bash", "command": "<str>",
   "working_directory": ".", "timeout_seconds": 30}
  {"id": "<uuid>", "action": "shutdown"}

RESPONSE:
  {"id": "<uuid>", "kind": "stdout"|"stderr", "data": "<chunk>"}
  {"id": "<uuid>", "kind": "exit", "exit_code": <int>, "duration_ms": <int>, "timed_out": <bool>}
  {"id": "<uuid>", "kind": "error", "message": "<str>"}

This file is INTENTIONALLY minimal. Full implementation is a Phase 2 deliverable.
"""

# TODO(phase-2): implement. See Issue 2.4 (`run_bash` tool).
# Acceptance:
#   - One running subprocess at a time per session (serialize via asyncio.Lock equivalent).
#   - stdout/stderr streamed back chunked, not buffered to end.
#   - SIGTERM after timeout, SIGKILL after timeout + 5s grace.
#   - Working directory restricted to /workspace and subdirs (validated, not assumed).
#   - Never run as root; entrypoint already drops to UID 1001.

raise NotImplementedError("sandbox/entrypoint.py — implement in Phase 2 (Issue 2.4)")
