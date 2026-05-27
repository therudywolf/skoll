"""File → text extractors.

Issue: phase-1.6.

Adapt vendor/ForestOptiLM/forestoptilm/file_extractors.py.
Handles: .py/.js/.ts/.md (read as text), .pdf (pypdf), .docx (python-docx),
.xlsx (openpyxl), .html (trafilatura), images (skip; vision tool handles).
"""

from __future__ import annotations

from pathlib import Path


def extract(path: Path) -> str:
    """Return plain text representation, raise UnsupportedExtractor on unknown."""
    # TODO(phase-1.6)
    raise NotImplementedError
