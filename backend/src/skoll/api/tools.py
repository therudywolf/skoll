"""Tool call approval endpoints.

Issue: phase-2.5.
Contracts: contracts/openapi.yaml.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# TODO(phase-2.5):
#   POST /sessions/{sid}/tool-calls/{tcid}/approve  — optionally with edited_args
#   POST /sessions/{sid}/tool-calls/{tcid}/reject   — with reason
# Both write to approval_log table for audit.
