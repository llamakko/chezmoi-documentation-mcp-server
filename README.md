# chezmoi Documentation MCP Server

Model Context Protocol (MCP) server for the official [chezmoi documentation](https://www.chezmoi.io/).

This server is inspired by the shape of the AWS documentation MCP server and focuses on the workflows that are most useful for docs-heavy assistants:

- Search the official chezmoi documentation
- Read a documentation page and convert it to Markdown
- Read specific sections from a documentation page
- List known documentation pages discovered from the site navigation

## Features

- Uses the official `https://www.chezmoi.io/` site as its source of truth
- Converts Material for MkDocs pages into LLM-friendly Markdown
- Builds and caches a local in-memory search index by crawling the docs site
- Restricts fetched content to the official chezmoi documentation host
- Runs over `stdio` by default

## Prerequisites

- Python 3.10 or newer
- An MCP client such as Claude Desktop, Cursor, or VS Code

## Installation

### Local development install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

### Example MCP client configuration

```json
{
  "mcpServers": {
    "chezmoi-documentation": {
      "command": "/ABSOLUTE/PATH/TO/chezmoi-documentation-mcp-server/.venv/bin/python",
      "args": ["-m", "chezmoi_documentation_mcp_server"],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR"
      }
    }
  }
}
```

If you publish the package, you can switch the command to `uvx` or your preferred package runner.

Prefer absolute paths and avoid wrapping the server launch in a shell command. This follows the MCP guidance for reducing local-server execution risk.

## Tools

### `search_documentation`

Search the official chezmoi documentation. The first search builds a cached index by crawling the site, so it may take longer than later searches.

Parameters:

- `query`: Search terms
- `limit`: Maximum number of results to return

### `read_documentation`

Fetch a chezmoi documentation page and convert the main content to Markdown.

Parameters:

- `url`: Absolute URL, root-relative path, or documentation path

### `read_sections`

Fetch a page and return only the requested sections.

Parameters:

- `url`: Absolute URL, root-relative path, or documentation path
- `sections`: A list of section names to match against page headings

### `list_documentation_pages`

List documentation pages discovered from the official site.

Parameters:

- `section`: Optional filter applied to URL and title
- `limit`: Maximum number of pages to return

## Environment variables

- `CHEZMOI_DOCUMENTATION_BASE_URL`: Base URL for docs crawling. Defaults to `https://www.chezmoi.io/`
- `CHEZMOI_DOCUMENTATION_ALLOW_UNOFFICIAL_BASE_URL`: Set to `true` only for local development against a non-official docs mirror
- `CHEZMOI_DOCUMENTATION_MAX_PAGES`: Maximum number of pages to crawl for the search index. Defaults to `350`
- `CHEZMOI_DOCUMENTATION_CONCURRENCY`: Concurrent fetches while building the index. Defaults to `10`
- `CHEZMOI_DOCUMENTATION_CACHE_TTL_SECONDS`: How long to keep the cached search index before refreshing. Defaults to `3600`
- `CHEZMOI_DOCUMENTATION_REQUEST_TIMEOUT_SECONDS`: HTTP timeout per request. Defaults to `20`
- `CHEZMOI_DOCUMENTATION_MAX_REDIRECTS`: Maximum redirects to follow after validating each hop. Defaults to `5`
- `CHEZMOI_DOCUMENTATION_MAX_RESPONSE_BYTES`: Maximum HTML response size in bytes. Defaults to `3145728`
- `CHEZMOI_DOCUMENTATION_MAX_DOCUMENT_CHARS`: Maximum Markdown/text characters returned from a page or section. Defaults to `120000`
- `CHEZMOI_DOCUMENTATION_MAX_QUERY_LENGTH`: Maximum search/filter query length. Defaults to `240`
- `CHEZMOI_DOCUMENTATION_MAX_SECTION_COUNT`: Maximum requested sections per call. Defaults to `12`
- `CHEZMOI_DOCUMENTATION_MAX_SECTION_LENGTH`: Maximum length of a section heading match string. Defaults to `120`
- `CHEZMOI_DOCUMENTATION_MAX_URL_LENGTH`: Maximum documentation URL length. Defaults to `2048`
- `CHEZMOI_DOCUMENTATION_MAX_SEARCH_RESULTS`: Upper bound for `search_documentation(limit=...)`. Defaults to `20`
- `CHEZMOI_DOCUMENTATION_MAX_LIST_RESULTS`: Upper bound for `list_documentation_pages(limit=...)`. Defaults to `200`
- `CHEZMOI_DOCUMENTATION_RATE_LIMIT_CALLS`: Maximum tool calls per process window. Defaults to `30`
- `CHEZMOI_DOCUMENTATION_RATE_LIMIT_PERIOD_SECONDS`: Rate-limit window length. Defaults to `60`
- `MCP_USER_AGENT`: Optional custom user agent for HTTP requests

## Security

This server applies a small set of MCP-aligned hardening measures:

- Validates tool inputs and rejects oversized URL, query, and section arguments
- Restricts fetches to the official chezmoi docs host by default
- Validates every redirect hop before following it
- Caps response size and returned document length
- Sanitizes returned text and Markdown
- Uses an in-memory rate limit for tool invocations
- Runs over `stdio` explicitly

Official MCP references used for these choices:

- MCP Security Best Practices: <https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices>
- MCP Tools Security Considerations: <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>
- MCP Transports (`stdio` guidance): <https://modelcontextprotocol.io/specification/2025-06-18/basic/transports>
- Build an MCP Server logging guidance: <https://modelcontextprotocol.io/docs/develop/build-server>

## Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Validate pinned GitHub Actions with pinact:

```bash
brew install pinact
pinact run --check
```

Update pinned GitHub Actions with pinact:

```bash
pinact run -u
```

## GitHub Release Setup

Before pushing a release tag, configure the `github-release` environment in your repository settings.

Recommended settings:

- Add required reviewers
- Enable `Prevent self-review`
- Restrict deployments to selected tags such as `v*`
- Disable admin bypass if your workflow allows it
- Add an environment variable named `RELEASE_ENV_READY` with the value `true`

The release workflow is intentionally configured to fail until `RELEASE_ENV_READY=true` is present in the `github-release` environment. This prevents accidentally publishing from an unprotected environment.

The workflow also verifies that the tagged commit is reachable from the repository default branch before it builds a release.

For public repositories, the release workflow generates artifact attestations for files in `dist/`. You can verify them with GitHub CLI:

```bash
gh attestation verify dist/* -R OWNER/REPO
```
