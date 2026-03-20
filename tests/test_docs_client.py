import unittest

from chezmoi_documentation_mcp_server.docs_client import (
    ChezmoiDocumentationClient,
    ServerConfig,
    extract_internal_links,
    page_to_search_document,
    parse_documentation_page,
    rank_documents,
)


SAMPLE_HTML = """
<!doctype html>
<html>
  <head>
    <title>init - chezmoi</title>
  </head>
  <body>
    <header>
      <a href="/">Home</a>
      <a href="/reference/commands/init/">Init</a>
      <a href="https://github.com/twpayne/chezmoi">GitHub</a>
      <a href="/assets/app.js">Asset</a>
    </header>
    <main>
      <article class="md-content__inner md-typeset">
        <h1 id="init">init</h1>
        <p>Initialize chezmoi from a local or remote source directory.</p>
        <h2 id="flags">Flags</h2>
        <p>Use <code>--apply</code> to apply after initialization.</p>
        <ul>
          <li><code>--apply</code> applies the target state immediately.</li>
        </ul>
        <h2 id="examples">Examples</h2>
        <pre><code>chezmoi init user --apply</code></pre>
      </article>
    </main>
  </body>
</html>
"""


def make_config() -> ServerConfig:
    return ServerConfig(
        base_url="https://www.chezmoi.io/",
        max_pages=50,
        concurrency=4,
        cache_ttl_seconds=3600,
        request_timeout_seconds=20.0,
        user_agent="test-agent",
        max_redirects=5,
        max_response_bytes=1024 * 1024,
        max_document_chars=20_000,
        max_query_length=240,
        max_section_count=12,
        max_section_length=120,
        max_url_length=2048,
        max_search_results=20,
        max_list_results=200,
        rate_limit_calls=30,
        rate_limit_period_seconds=60,
    )


class ExtractInternalLinksTests(unittest.TestCase):
    def test_extract_internal_links_filters_external_and_assets(self) -> None:
        links = extract_internal_links(SAMPLE_HTML, "https://www.chezmoi.io/")
        self.assertEqual(
            links,
            [
                "https://www.chezmoi.io/",
                "https://www.chezmoi.io/reference/commands/init/",
            ],
        )


class ParseDocumentationPageTests(unittest.TestCase):
    def test_parse_documentation_page_extracts_title_summary_and_sections(self) -> None:
        page = parse_documentation_page(
            SAMPLE_HTML,
            "https://www.chezmoi.io/reference/commands/init/",
            "https://www.chezmoi.io/",
        )

        self.assertEqual(page.title, "init")
        self.assertEqual(page.summary, "Initialize chezmoi from a local or remote source directory.")
        self.assertEqual(page.headings, ["init", "Flags", "Examples"])
        self.assertEqual([section.heading for section in page.sections], ["init", "Flags", "Examples"])
        self.assertIn("# init", page.markdown)
        self.assertIn("`--apply`", page.markdown)


class SearchRankingTests(unittest.TestCase):
    def test_rank_documents_prefers_best_title_and_heading_match(self) -> None:
        init_page = parse_documentation_page(
            SAMPLE_HTML,
            "https://www.chezmoi.io/reference/commands/init/",
            "https://www.chezmoi.io/",
        )
        apply_page = parse_documentation_page(
            """
            <html>
              <body>
                <main>
                  <article class="md-content__inner">
                    <h1>apply</h1>
                    <p>Apply the target state to the destination directory.</p>
                  </article>
                </main>
              </body>
            </html>
            """,
            "https://www.chezmoi.io/reference/commands/apply/",
            "https://www.chezmoi.io/",
        )

        results = rank_documents(
            "init apply",
            [page_to_search_document(init_page), page_to_search_document(apply_page)],
            limit=2,
        )

        self.assertEqual(results[0].title, "init")
        self.assertGreaterEqual(results[0].score, results[1].score)
        self.assertEqual(len(results), 2)


class ClientValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_rejects_overlong_query(self) -> None:
        client = ChezmoiDocumentationClient(make_config())

        with self.assertRaisesRegex(ValueError, "query"):
            await client.search("x" * 241)

    async def test_read_sections_rejects_too_many_sections(self) -> None:
        client = ChezmoiDocumentationClient(make_config())

        with self.assertRaisesRegex(ValueError, "at most"):
            await client.read_sections(
                "https://www.chezmoi.io/reference/commands/init/",
                [f"section-{index}" for index in range(13)],
            )

    def test_normalize_url_rejects_external_hosts(self) -> None:
        client = ChezmoiDocumentationClient(make_config())

        with self.assertRaisesRegex(ValueError, "configured chezmoi base host"):
            client.normalize_url("https://example.com/")


if __name__ == "__main__":
    unittest.main()
