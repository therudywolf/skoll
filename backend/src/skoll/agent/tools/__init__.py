"""Agent tools.

Each tool lives in its own module and implements the ToolProtocol from registry.py.
The JSON schemas in contracts/tools/ are the source of truth — registry validates
that each module's declared schema matches the file on disk.
"""
