"""Workspace file CRUD.

Issue: phase-1.* (read), phase-2.* (write with audit log).
Contracts: contracts/openapi.yaml.

Every file path passes through skoll.security.path.safe_resolve.
Every read passes through skoll.security.secrets.scrub.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# TODO: GET /workspaces/{id}/files, GET /workspaces/{id}/files/content, PUT same
