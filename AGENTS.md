# AGENTS.md

## Purpose

This repository contains a local MCP server for the official chezmoi documentation site.

Core responsibilities:

- Search the official chezmoi docs
- Read and convert docs pages to Markdown
- Extract specific sections from docs pages
- Stay safe-by-default for local MCP usage

## Architecture

- Entry point: `src/chezmoi_documentation_mcp_server/server.py`
- Docs crawling, parsing, indexing, and tool guardrails: `src/chezmoi_documentation_mcp_server/docs_client.py`
- Tests: `tests/test_docs_client.py`

## Security Baseline

When changing this project, preserve these defaults unless the user explicitly asks otherwise:

- Keep the server on `stdio` transport by default
- Never add stdout logging; use stderr-only logging if logging is needed
- Keep official-host allowlisting on by default for docs fetches
- Keep per-hop redirect validation in place
- Keep input size limits, response size caps, and output sanitization in place
- Keep tool rate limiting in place unless replaced by something stricter
- Do not add shell-based launch examples to the README
- Do not expand the fetch surface beyond the official docs host without documenting the risk
- Keep the `github-release` environment gate and release-tag ancestry check in place
- Keep build provenance attestation enabled for supported repositories

## MCP References

Use these as the primary sources when making security-sensitive changes:

- Security Best Practices: <https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices>
- Tools security considerations: <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>
- Transports / `stdio`: <https://modelcontextprotocol.io/specification/2025-06-18/basic/transports>
- Build server logging guidance: <https://modelcontextprotocol.io/docs/develop/build-server>

## Change Guidelines

- Prefer additive hardening over broader capability
- If adding HTTP transport, OAuth, or remote hosting, do a separate security review
- If relaxing host restrictions for development, gate it behind an explicit env var
- Add or update tests for parser behavior and security validation whenever practical
- Keep README security notes in sync with the implementation
