from __future__ import annotations

import argparse
import asyncio
import json
import sys

from chezmoi_documentation_mcp_server.docs_client import ChezmoiDocumentationClient, ServerConfig


DEFAULT_PAGE_URL = "https://www.chezmoi.io/reference/commands/init/"
DEFAULT_SECTION = "Flags"


async def run_smoke_check(page_url: str, section_name: str) -> int:
    client = ChezmoiDocumentationClient(ServerConfig.from_env())
    try:
        page = await client.fetch_page(page_url)
        section_result = await client.read_sections(page_url, [section_name])
    finally:
        await client.aclose()

    matched_sections = section_result["matched_sections"]
    missing_sections = section_result["missing_sections"]

    errors: list[str] = []
    if not page.title:
        errors.append("page title is empty")
    if "init" not in page.title.lower():
        errors.append(f"unexpected page title: {page.title!r}")
    if len(page.headings) < 2:
        errors.append("expected at least two headings on the smoke-check page")
    if len(page.markdown.strip()) < 100:
        errors.append("page markdown is unexpectedly short")
    if not matched_sections:
        errors.append(f"section {section_name!r} was not found")
    if missing_sections:
        errors.append(f"missing sections reported: {missing_sections!r}")

    payload = {
        "page_url": page_url,
        "page_title": page.title,
        "heading_count": len(page.headings),
        "matched_section_count": len(matched_sections),
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False))

    if errors:
        for error in errors:
            print(f"smoke-check error: {error}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a low-impact smoke check against the official chezmoi docs site.")
    parser.add_argument("--page-url", default=DEFAULT_PAGE_URL, help="Documentation page to fetch for the smoke check.")
    parser.add_argument("--section", default=DEFAULT_SECTION, help="Heading to verify on the smoke-check page.")
    args = parser.parse_args()
    return asyncio.run(run_smoke_check(page_url=args.page_url, section_name=args.section))


if __name__ == "__main__":
    raise SystemExit(main())
