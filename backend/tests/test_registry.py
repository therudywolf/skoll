"""Tests for the tool registry (Issue 1.5).

No network / LM Studio needed — the registry only reads contracts/tools/*.json and binds the
module-level ``handler`` callables (which are themselves stubs that raise NotImplementedError).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from skoll.agent.tools.registry import (
    Tool,
    ToolContext,
    ToolRegistry,
    ToolSchema,
)
from skoll.errors import ToolError, ToolValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_TOOLS = REPO_ROOT / "contracts" / "tools"

# A placeholder workspace root for ToolContext; never actually read by these tests
# (arg validation runs before the handler, and the handlers are NotImplementedError stubs).
WS_ROOT = "workspace"

# Known tool → phase mapping from contracts/tools/.
PHASE_1_TOOLS = {"codebase_search", "read_file"}
PHASE_2_TOOLS = {"write_file", "apply_diff", "run_bash", "web_search", "read_url"}
PHASE_3_TOOLS = {"analyze_corpus", "analyze_image", "git_diff", "git_commit"}


def _load_phase1() -> ToolRegistry:
    return ToolRegistry.load_from_contracts(str(CONTRACTS_TOOLS), enabled_phases={"1"})


def test_contracts_dir_exists() -> None:
    assert CONTRACTS_TOOLS.is_dir()
    assert list(CONTRACTS_TOOLS.glob("*.json"))


def test_load_registers_phase1_tools() -> None:
    reg = _load_phase1()
    names = set(reg.names())
    assert PHASE_1_TOOLS <= names
    # Phase 2/3 tools must NOT be present when only phase 1 is enabled.
    assert names.isdisjoint(PHASE_2_TOOLS)
    assert names.isdisjoint(PHASE_3_TOOLS)


def test_phase_gating_enables_more_with_more_phases() -> None:
    reg = ToolRegistry.load_from_contracts(str(CONTRACTS_TOOLS), enabled_phases={"1", "2", "3"})
    names = set(reg.names())
    assert PHASE_1_TOOLS <= names
    assert PHASE_2_TOOLS <= names
    assert PHASE_3_TOOLS <= names
    # All 11 descriptors registered.
    assert len(reg) == len(list(CONTRACTS_TOOLS.glob("*.json")))


def test_get_returns_tool_with_bound_handler() -> None:
    reg = _load_phase1()
    tool = reg.get("read_file")
    assert isinstance(tool, Tool)
    assert tool.schema.name == "read_file"
    assert callable(tool.handler)


def test_get_unknown_tool_raises_tool_error() -> None:
    reg = _load_phase1()
    with pytest.raises(ToolError):
        reg.get("does_not_exist")


def test_contains_and_len() -> None:
    reg = _load_phase1()
    assert "read_file" in reg
    assert "write_file" not in reg
    assert len(reg) == len(PHASE_1_TOOLS)


def test_openai_schemas_shape() -> None:
    reg = _load_phase1()
    schemas = reg.openai_schemas()
    assert schemas
    by_name = {s["function"]["name"]: s for s in schemas}
    assert PHASE_1_TOOLS <= set(by_name)
    for schema in schemas:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert set(fn) == {"name", "description", "parameters"}
        assert isinstance(fn["name"], str)
        assert isinstance(fn["description"], str) and fn["description"]
        assert fn["parameters"]["type"] == "object"

    # The parameters block is exactly the descriptor's `parameters` field.
    rf = json.loads((CONTRACTS_TOOLS / "read_file.json").read_text(encoding="utf-8"))
    assert by_name["read_file"]["function"]["parameters"] == rf["parameters"]


def test_register_rejects_duplicate() -> None:
    reg = _load_phase1()
    existing = reg.get("read_file")
    with pytest.raises(ToolError):
        reg.register(existing)


def test_load_rejects_descriptor_with_missing_module(tmp_path: Path) -> None:
    # Copy a real descriptor but rename it to a tool with no implementation module.
    src = json.loads((CONTRACTS_TOOLS / "read_file.json").read_text(encoding="utf-8"))
    src["name"] = "totally_missing_tool"
    (tmp_path / "totally_missing_tool.json").write_text(json.dumps(src), encoding="utf-8")

    with pytest.raises(ToolError):
        ToolRegistry.load_from_contracts(str(tmp_path), enabled_phases={"1"})


def test_load_rejects_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ToolError):
        ToolRegistry.load_from_contracts(str(tmp_path), enabled_phases={"1"})


def test_load_rejects_missing_required_field(tmp_path: Path) -> None:
    (tmp_path / "incomplete.json").write_text(
        json.dumps({"name": "incomplete", "phase": "1"}), encoding="utf-8"
    )
    with pytest.raises(ToolError):
        ToolRegistry.load_from_contracts(str(tmp_path), enabled_phases={"1"})


def test_load_missing_contracts_dir_raises() -> None:
    with pytest.raises(ToolError):
        ToolRegistry.load_from_contracts(
            str(REPO_ROOT / "no" / "such" / "dir"), enabled_phases={"1"}
        )


def test_validate_args_accepts_valid_and_rejects_invalid() -> None:
    reg = _load_phase1()
    # Valid: read_file requires `path` (string).
    reg.validate_args("read_file", {"path": "src/auth.py"})

    # Missing required `path`.
    with pytest.raises(ToolValidationError):
        reg.validate_args("read_file", {})

    # Wrong type for `path`.
    with pytest.raises(ToolValidationError):
        reg.validate_args("read_file", {"path": 123})

    # additionalProperties: false → unknown key rejected.
    with pytest.raises(ToolValidationError):
        reg.validate_args("read_file", {"path": "a.py", "bogus": 1})


async def test_execute_validates_before_invoking_handler() -> None:
    reg = _load_phase1()
    ctx = ToolContext(session_id="s1", workspace_root=WS_ROOT)
    # Bad args must raise ToolValidationError without ever reaching the (stub) handler.
    with pytest.raises(ToolValidationError):
        await reg.execute("read_file", {}, ctx)


async def test_execute_invokes_handler_after_validation() -> None:
    # With valid args, execution reaches the stub handler which raises NotImplementedError.
    reg = _load_phase1()
    ctx = ToolContext(session_id="s1", workspace_root=WS_ROOT)
    with pytest.raises(NotImplementedError):
        await reg.execute("read_file", {"path": "src/auth.py"}, ctx)


async def test_execute_unknown_tool_raises_tool_error() -> None:
    reg = _load_phase1()
    ctx = ToolContext(session_id="s1", workspace_root=WS_ROOT)
    with pytest.raises(ToolError):
        await reg.execute("nope", {"path": "x"}, ctx)


def test_register_and_get_custom_tool() -> None:
    # A hand-built Tool round-trips through register/get/openai_schemas.
    async def _handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return {"ok": True}

    schema = ToolSchema(
        name="custom_tool",
        description="custom",
        phase="1",
        kind="read",
        requires_approval=False,
        auto_approve_default=True,
        path_args=[],
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        result_schema={"type": "object"},
    )
    reg = ToolRegistry()
    reg.register(Tool(schema=schema, handler=_handler))
    assert reg.get("custom_tool").schema.description == "custom"
    assert reg.openai_schemas()[0]["function"]["name"] == "custom_tool"
