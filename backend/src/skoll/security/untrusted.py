"""Untrusted content wrapping.

Issue: phase-1.11.
Spec: prompts/untrusted_content_wrapper.md.
"""

from __future__ import annotations


def wrap(
    content: str,
    *,
    source: str,  # 'file' | 'url' | 'web_search' | 'tool_result'
    **metadata: str | int | bool,
) -> str:
    """Wrap external content in <untrusted_content> tags with provenance metadata.

    Example output:
        <untrusted_content source="file" path="src/auth.py" lines="1-42" secrets_redacted="2">
        ...
        </untrusted_content>
    """
    # TODO(phase-1.11)
    raise NotImplementedError
