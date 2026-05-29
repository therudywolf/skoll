"""Untrusted content wrapping.

Issue: phase-1.11.
Spec: prompts/untrusted_content_wrapper.md.

Wraps anything the agent reads from outside the system prompt / tool definitions (file
content, fetched URLs, search results, external tool output) in
``<untrusted_content>...</untrusted_content>`` tags with provenance metadata. The system
prompt instructs the model to treat everything inside those tags as data, never commands.

Critically, the wrapper neutralises any attempt by the content itself to break out of the
tags: a literal ``</untrusted_content>`` embedded in the payload (or a forged opening tag)
is defanged so the model still sees a single, well-formed untrusted block.
"""

from __future__ import annotations

import re

TAG = "untrusted_content"

# Match either an opening or closing `untrusted_content` tag, case-insensitively, regardless
# of surrounding whitespace/attributes, so embedded payloads cannot forge or close the block.
_TAG_RE = re.compile(r"<\s*/?\s*untrusted_content\b[^>]*>", re.IGNORECASE)


def _neutralize(content: str) -> str:
    """Defang any literal untrusted_content tag inside the payload.

    The angle brackets are HTML-entity-encoded so the sequence can never be re-parsed as the
    real delimiter, while remaining human-readable in the transcript.
    """

    def _escape(match: re.Match[str]) -> str:
        return match.group(0).replace("<", "&lt;").replace(">", "&gt;")

    return _TAG_RE.sub(_escape, content)


def _attr_value(value: str | int | bool) -> str:
    """Render a metadata value as a safe double-quoted attribute string.

    Booleans become ``true``/``false``; everything else is stringified with characters that
    could break out of the attribute (quotes, angle brackets, newlines) escaped.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", " ")
        .replace("\r", " ")
    )


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

    ``source`` becomes the leading attribute; remaining keyword metadata is appended as
    attributes in call order. Both attribute values and the payload are sanitised so neither
    can break out of the tag structure.
    """
    attrs = [f'source="{_attr_value(source)}"']
    attrs.extend(f'{key}="{_attr_value(val)}"' for key, val in metadata.items())
    attr_str = " ".join(attrs)

    safe = _neutralize(content)
    return f"<{TAG} {attr_str}>\n{safe}\n</{TAG}>"
