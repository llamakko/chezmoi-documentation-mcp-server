from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .docs_client import ChezmoiDocumentationClient, ServerConfig


def create_server() -> FastMCP:
    config = ServerConfig.from_env()
    client = ChezmoiDocumentationClient(config)
    server = FastMCP(
        "chezmoi-documentation-mcp-server",
        instructions=(
            "Use these tools to search and read the official chezmoi documentation. "
            "Prefer official docs URLs on https://www.chezmoi.io/ and cite returned source URLs."
        ),
        dependencies=[
            "beautifulsoup4",
            "httpx",
            "markdownify",
        ],
    )

    @server.tool()
    async def search_documentation(query: str, limit: int = 10) -> dict[str, object]:
        """Search the official chezmoi documentation and return ranked matches."""

        return await client.search(query=query, limit=limit)

    @server.tool()
    async def read_documentation(url: str) -> dict[str, object]:
        """Read a chezmoi documentation page and convert its main content to Markdown."""

        return await client.read_documentation(url=url)

    @server.tool()
    async def read_sections(url: str, sections: list[str]) -> dict[str, object]:
        """Read selected sections from a chezmoi documentation page."""

        return await client.read_sections(url=url, sections=sections)

    @server.tool()
    async def list_documentation_pages(section: str | None = None, limit: int = 100) -> dict[str, object]:
        """List documentation pages discovered from the official chezmoi documentation site."""

        return await client.list_documentation_pages(section=section, limit=limit)

    return server


def main() -> None:
    create_server().run(transport="stdio")
