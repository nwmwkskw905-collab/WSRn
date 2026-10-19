"""Minimal MCP (Model Context Protocol) server exposing JARVIS tools over stdio.

No third-party SDK: the protocol used here is JSON-RPC 2.0 with the
`initialize` / `tools/list` / `tools/call` methods from the MCP spec (2024-11-05).
"""
