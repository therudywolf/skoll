"""Sandbox lifecycle from the backend side.

Issue: phase-1.10 (start/stop), phase-2.4 (control protocol).

For each active session, the backend may have an ephemeral sandbox container.
This module manages the Docker SDK calls and the stdin/stdout JSON channel.
"""
