"""apply_diff tool — SEARCH/REPLACE format. REQUIRES APPROVAL.

Issue: phase-2.3.
Schema: contracts/tools/apply_diff.json.
Format spec: prompts/edit_format.md.

Implementation notes:
  - Apply blocks SEQUENTIALLY; later blocks see earlier blocks' replacements
  - For each block: check search appears exactly once (else: search_ambiguous or search_not_found)
  - On any failure, do NOT partially write — collect all failures, return them, leave file unchanged
  - Optional fuzzy fallback (Aider-style): if exact match fails, try whitespace-normalized match;
    on success, log a warning but proceed
"""

from __future__ import annotations

from typing import Any


async def handler(args: dict[str, Any], context: Any) -> dict[str, Any]:
    # TODO(phase-2.3)
    raise NotImplementedError
