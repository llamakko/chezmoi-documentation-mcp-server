from __future__ import annotations

import asyncio
import os
import re
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from typing import Iterable
from urllib.parse import urljoin, urlparse, urldefrag

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import markdownify

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
OFFICIAL_BASE_HOSTS = frozenset({"www.chezmoi.io", "chezmoi.io"})
EXCLUDED_PATH_PREFIXES = ("/assets/", "/blog/", "/search/")
EXCLUDED_EXTENSIONS = {
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".png",
    ".svg",
    ".txt",
    ".webmanifest",
    ".xml",
}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]{1,}")
WHITESPACE_RE = re.compile(r"\s+")
MARKDOWN_GAP_RE = re.compile(r"\n{3,}")
TRUNCATED_SUFFIX = "\n\n[Truncated]"


@dataclass(slots=True)
class ServerConfig:
    base_url: str
    max_pages: int
    concurrency: int
    cache_ttl_seconds: int
    request_timeout_seconds: float
    user_agent: str
    max_redirects: int
    max_response_bytes: int
    max_document_chars: int
    max_query_length: int
    max_section_count: int
    max_section_length: int
    max_url_length: int
    max_search_results: int
    max_list_results: int
    rate_limit_calls: int
    rate_limit_period_seconds: int

    @classmethod
    def from_env(cls) -> "ServerConfig":
        allow_unofficial_base_url = parse_bool_env("CHEZMOI_DOCUMENTATION_ALLOW_UNOFFICIAL_BASE_URL")
        base_url = normalize_base_url(
            os.getenv("CHEZMOI_DOCUMENTATION_BASE_URL", "https://www.chezmoi.io/"),
            allow_unofficial_base_url=allow_unofficial_base_url,
        )
        return cls(
            base_url=base_url,
            max_pages=max(1, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_PAGES", "350"))),
            concurrency=max(1, int(os.getenv("CHEZMOI_DOCUMENTATION_CONCURRENCY", "10"))),
            cache_ttl_seconds=max(60, int(os.getenv("CHEZMOI_DOCUMENTATION_CACHE_TTL_SECONDS", "3600"))),
            request_timeout_seconds=max(
                1.0,
                float(os.getenv("CHEZMOI_DOCUMENTATION_REQUEST_TIMEOUT_SECONDS", "20")),
            ),
            user_agent=os.getenv(
                "MCP_USER_AGENT",
                "chezmoi-documentation-mcp-server/0.1.0 (+https://www.chezmoi.io/)",
            ),
            max_redirects=max(0, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_REDIRECTS", "5"))),
            max_response_bytes=max(16_384, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_RESPONSE_BYTES", "3145728"))),
            max_document_chars=max(2_048, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_DOCUMENT_CHARS", "120000"))),
            max_query_length=max(8, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_QUERY_LENGTH", "240"))),
            max_section_count=max(1, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_SECTION_COUNT", "12"))),
            max_section_length=max(4, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_SECTION_LENGTH", "120"))),
            max_url_length=max(32, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_URL_LENGTH", "2048"))),
            max_search_results=max(1, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_SEARCH_RESULTS", "20"))),
            max_list_results=max(1, int(os.getenv("CHEZMOI_DOCUMENTATION_MAX_LIST_RESULTS", "200"))),
            rate_limit_calls=max(1, int(os.getenv("CHEZMOI_DOCUMENTATION_RATE_LIMIT_CALLS", "30"))),
            rate_limit_period_seconds=max(
                1,
                int(os.getenv("CHEZMOI_DOCUMENTATION_RATE_LIMIT_PERIOD_SECONDS", "60")),
            ),
        )


def parse_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_base_url(base_url: str, *, allow_unofficial_base_url: bool) -> str:
    candidate = base_url.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("CHEZMOI_DOCUMENTATION_BASE_URL must be an absolute http(s) URL")
    if not allow_unofficial_base_url:
        if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_BASE_HOSTS:
            raise ValueError(
                "Only the official HTTPS chezmoi documentation hosts are allowed by default. "
                "Set CHEZMOI_DOCUMENTATION_ALLOW_UNOFFICIAL_BASE_URL=true only for local development."
            )
    normalized_path = parsed.path or "/"
    if not normalized_path.endswith("/"):
        normalized_path = f"{normalized_path}/"
    return parsed._replace(path=normalized_path, params="", query="", fragment="").geturl()


@dataclass(slots=True)
class DocumentationSection:
    heading: str
    level: int
    anchor: str | None
    markdown: str
    text: str


@dataclass(slots=True)
class DocumentationPage:
    title: str
    url: str
    summary: str
    markdown: str
    text: str
    headings: list[str]
    sections: list[DocumentationSection]
    links: list[str]


@dataclass(slots=True)
class SearchDocument:
    title: str
    url: str
    summary: str
    headings: list[str]
    body_text: str
    path: str
    title_counter: Counter[str] = field(repr=False)
    headings_counter: Counter[str] = field(repr=False)
    body_counter: Counter[str] = field(repr=False)
    title_lower: str = field(repr=False)
    headings_lower: str = field(repr=False)
    body_lower: str = field(repr=False)


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    summary: str
    snippet: str
    headings: list[str]
    score: float


def normalize_site_url(url: str, base_url: str) -> str | None:
    if not url:
        return None
    candidate = url.strip()
    if not candidate or candidate.startswith(("#", "mailto:", "javascript:", "tel:")):
        return None
    absolute, _ = urldefrag(urljoin(base_url, candidate))
    parsed = urlparse(absolute)
    base = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc != base.netloc:
        return None
    path = parsed.path or "/"
    if any(path.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES):
        return None
    extension = os.path.splitext(path)[1].lower()
    if extension and extension in EXCLUDED_EXTENSIONS:
        return None
    if extension and extension not in {".html"}:
        return None
    if path in {"/404.html", "/sitemap.xml"}:
        return None
    return parsed._replace(query="").geturl()


def extract_internal_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        normalized = normalize_site_url(anchor.get("href", ""), base_url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    return links


def sanitize_text(text: str, max_chars: int | None = None) -> str:
    sanitized = "".join(char for char in text if char in {"\n", "\r", "\t"} or ord(char) >= 32)
    if max_chars is not None and len(sanitized) > max_chars:
        truncated = sanitized[:max_chars].rstrip()
        return f"{truncated}{TRUNCATED_SUFFIX}"
    return sanitized


def collapse_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", sanitize_text(text)).strip()


def normalize_markdown(text: str) -> str:
    return sanitize_text(MARKDOWN_GAP_RE.sub("\n\n", text).strip())


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def locate_main_content(soup: BeautifulSoup) -> Tag:
    selectors = (
        "main article.md-content__inner",
        "article.md-content__inner",
        "main .md-content__inner",
        "main article",
        "article",
        "main",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            return node
    if isinstance(soup.body, Tag):
        return soup.body
    return soup


def prune_content(content: Tag) -> None:
    selectors = (
        "script",
        "style",
        "nav",
        ".headerlink",
        ".md-content__button",
        ".md-source-file",
        ".md-feedback",
        ".md-typeset .footnote-backref",
    )
    for selector in selectors:
        for node in content.select(selector):
            node.decompose()


def render_markdown(html: str) -> str:
    return normalize_markdown(
        markdownify(
            html,
            heading_style="ATX",
            bullets="-",
            strip=["button"],
        )
    )


def pick_summary(content: Tag, fallback_text: str) -> str:
    for tag in content.find_all(["p", "li"], recursive=True):
        text = collapse_whitespace(tag.get_text(" ", strip=True))
        if len(text) >= 40:
            return text
    return collapse_whitespace(fallback_text)[:240]


def extract_sections(content: Tag, fallback_title: str) -> list[DocumentationSection]:
    sections: list[DocumentationSection] = []
    current_heading = fallback_title
    current_level = 1
    current_anchor: str | None = None
    current_nodes: list[Tag | NavigableString] = []

    for child in content.children:
        if isinstance(child, NavigableString):
            if child.strip():
                current_nodes.append(child)
            continue
        if not isinstance(child, Tag):
            continue
        if child.name in HEADING_TAGS:
            if current_nodes:
                html = "".join(str(node) for node in current_nodes)
                text = collapse_whitespace(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
                if text:
                    sections.append(
                        DocumentationSection(
                            heading=current_heading,
                            level=current_level,
                            anchor=current_anchor,
                            markdown=render_markdown(html),
                            text=text,
                        )
                    )
            current_heading = collapse_whitespace(child.get_text(" ", strip=True)) or fallback_title
            current_level = int(child.name[1])
            current_anchor = child.get("id")
            current_nodes = [child]
            continue
        current_nodes.append(child)

    if current_nodes:
        html = "".join(str(node) for node in current_nodes)
        text = collapse_whitespace(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
        if text:
            sections.append(
                DocumentationSection(
                    heading=current_heading,
                    level=current_level,
                    anchor=current_anchor,
                    markdown=render_markdown(html),
                    text=text,
                )
            )

    if sections:
        return sections

    html = str(content)
    text = collapse_whitespace(content.get_text(" ", strip=True))
    return [
        DocumentationSection(
            heading=fallback_title,
            level=1,
            anchor=None,
            markdown=render_markdown(html),
            text=text,
        )
    ]


def parse_documentation_page(
    html: str,
    url: str,
    base_url: str,
    *,
    max_document_chars: int = 120_000,
) -> DocumentationPage:
    soup = BeautifulSoup(html, "html.parser")
    content = locate_main_content(soup)
    prune_content(content)

    title_tag = content.find("h1")
    if title_tag is not None:
        title = collapse_whitespace(title_tag.get_text(" ", strip=True))
    elif soup.title is not None:
        title = collapse_whitespace(soup.title.get_text(" ", strip=True)).split(" - chezmoi", 1)[0]
    else:
        title = urlparse(url).path.rstrip("/").split("/")[-1] or "chezmoi"

    markdown = sanitize_text(render_markdown(str(content)), max_chars=max_document_chars)
    text = sanitize_text(collapse_whitespace(content.get_text(" ", strip=True)), max_chars=max_document_chars)
    headings = [
        sanitize_text(collapse_whitespace(heading.get_text(" ", strip=True)), max_chars=240)
        for heading in content.find_all(HEADING_TAGS)
        if collapse_whitespace(heading.get_text(" ", strip=True))
    ]
    sections = extract_sections(content, fallback_title=title)
    summary = sanitize_text(pick_summary(content, text), max_chars=600)

    return DocumentationPage(
        title=title,
        url=url,
        summary=summary,
        markdown=markdown,
        text=text,
        headings=headings,
        sections=sections,
        links=extract_internal_links(html, base_url),
    )


def page_to_search_document(page: DocumentationPage) -> SearchDocument:
    headings_text = " ".join(page.headings)
    return SearchDocument(
        title=page.title,
        url=page.url,
        summary=page.summary,
        headings=page.headings,
        body_text=page.text,
        path=urlparse(page.url).path.lower(),
        title_counter=Counter(tokenize(page.title)),
        headings_counter=Counter(tokenize(headings_text)),
        body_counter=Counter(tokenize(page.text)),
        title_lower=page.title.lower(),
        headings_lower=headings_text.lower(),
        body_lower=page.text.lower(),
    )


def build_snippet(text: str, query_tokens: list[str], max_length: int = 240) -> str:
    if not text:
        return ""
    lowered = text.lower()
    first_match = -1
    for token in query_tokens:
        position = lowered.find(token)
        if position != -1 and (first_match == -1 or position < first_match):
            first_match = position
    if first_match == -1:
        return text[:max_length].strip()

    start = max(0, first_match - 60)
    end = min(len(text), first_match + max_length - 60)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = f"...{snippet}"
    if end < len(text):
        snippet = f"{snippet}..."
    return snippet


def score_document(document: SearchDocument, query: str, query_tokens: list[str]) -> float:
    if not query_tokens:
        return 0.0

    score = 0.0
    query_lower = query.lower()
    if query_lower in document.title_lower:
        score += 40.0
    if query_lower in document.headings_lower:
        score += 24.0
    if query_lower in document.body_lower:
        score += 12.0
    if query_lower in document.path:
        score += 16.0

    matched_tokens = 0
    for token in query_tokens:
        token_score = 0.0
        if token in document.title_counter:
            token_score += 8.0 * min(document.title_counter[token], 3)
        if token in document.headings_counter:
            token_score += 4.0 * min(document.headings_counter[token], 4)
        if token in document.body_counter:
            token_score += 1.0 * min(document.body_counter[token], 8)
        if token in document.path:
            token_score += 2.0
        if token_score > 0:
            matched_tokens += 1
        score += token_score

    coverage = matched_tokens / len(query_tokens)
    if coverage == 1:
        score += 10.0
    else:
        score += coverage * 5.0
    return score


def rank_documents(query: str, documents: Iterable[SearchDocument], limit: int = 10) -> list[SearchResult]:
    query_tokens = tokenize(query)
    ranked: list[SearchResult] = []
    for document in documents:
        score = score_document(document, query, query_tokens)
        if score <= 0:
            continue
        ranked.append(
            SearchResult(
                title=document.title,
                url=document.url,
                summary=document.summary,
                snippet=build_snippet(document.body_text, query_tokens),
                headings=document.headings[:6],
                score=round(score, 2),
            )
        )

    ranked.sort(key=lambda item: (-item.score, item.title.lower(), item.url))
    return ranked[: max(1, limit)]


def normalize_heading(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", heading.lower()).strip()


class ChezmoiDocumentationClient:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._page_cache: dict[str, DocumentationPage] = {}
        self._search_index: list[SearchDocument] | None = None
        self._index_built_at: float = 0.0
        self._index_lock = asyncio.Lock()
        self._rate_limit_lock = asyncio.Lock()
        self._tool_call_times: deque[float] = deque()

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                    "User-Agent": self.config.user_agent,
                },
                follow_redirects=False,
                timeout=self.config.request_timeout_seconds,
            )
        return self._client

    async def _enforce_rate_limit(self) -> None:
        async with self._rate_limit_lock:
            now = time.monotonic()
            while self._tool_call_times and now - self._tool_call_times[0] >= self.config.rate_limit_period_seconds:
                self._tool_call_times.popleft()
            if len(self._tool_call_times) >= self.config.rate_limit_calls:
                raise ValueError("Rate limit exceeded. Please retry in a moment.")
            self._tool_call_times.append(now)

    def _validate_limit(self, limit: int, *, maximum: int, name: str = "limit") -> int:
        if limit < 1 or limit > maximum:
            raise ValueError(f"{name} must be between 1 and {maximum}")
        return limit

    def _validate_query(self, query: str) -> str:
        normalized_query = collapse_whitespace(query)
        if not normalized_query:
            raise ValueError("query must not be empty")
        if len(normalized_query) > self.config.max_query_length:
            raise ValueError(f"query must be at most {self.config.max_query_length} characters")
        return normalized_query

    def _validate_sections_input(self, sections: list[str]) -> list[str]:
        if not sections:
            raise ValueError("sections must contain at least one heading")
        if len(sections) > self.config.max_section_count:
            raise ValueError(f"sections must contain at most {self.config.max_section_count} headings")

        validated: list[str] = []
        for section in sections:
            normalized_section = collapse_whitespace(section)
            if not normalized_section:
                continue
            if len(normalized_section) > self.config.max_section_length:
                raise ValueError(f"each section name must be at most {self.config.max_section_length} characters")
            validated.append(normalized_section)
        if not validated:
            raise ValueError("sections must contain at least one non-empty heading")
        return validated

    def normalize_url(self, url: str) -> str:
        if len(url.strip()) > self.config.max_url_length:
            raise ValueError(f"url must be at most {self.config.max_url_length} characters")
        normalized = normalize_site_url(url, self.config.base_url)
        if normalized is None:
            raise ValueError(
                "Only documentation URLs on the configured chezmoi base host are supported. "
                "Pass an absolute URL on the configured host or a docs path."
            )
        return normalized

    async def _fetch_html(self, url: str) -> tuple[str, str]:
        current_url = self.normalize_url(url)
        redirects_remaining = self.config.max_redirects
        client = await self._get_http_client()

        while True:
            async with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Received a redirect without a Location header")
                    if redirects_remaining <= 0:
                        raise ValueError("Too many redirects while fetching documentation")
                    redirects_remaining -= 1
                    current_url = self.normalize_url(urljoin(str(response.url), location))
                    continue

                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if content_type and "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    raise ValueError(f"Unexpected content type: {content_type}")

                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit() and int(content_length) > self.config.max_response_bytes:
                    raise ValueError(
                        f"Documentation response exceeded the configured size limit of "
                        f"{self.config.max_response_bytes} bytes"
                    )

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self.config.max_response_bytes:
                        raise ValueError(
                            f"Documentation response exceeded the configured size limit of "
                            f"{self.config.max_response_bytes} bytes"
                        )

                html = body.decode(response.encoding or "utf-8", errors="replace")
                return self.normalize_url(str(response.url)), html

    async def fetch_page(self, url: str) -> DocumentationPage:
        normalized = self.normalize_url(url)
        cached = self._page_cache.get(normalized)
        if cached is not None:
            return cached

        canonical_url, html = await self._fetch_html(normalized)
        page = parse_documentation_page(
            html,
            canonical_url,
            self.config.base_url,
            max_document_chars=self.config.max_document_chars,
        )
        self._page_cache[normalized] = page
        self._page_cache[canonical_url] = page
        return page

    def _search_index_is_fresh(self) -> bool:
        return (
            self._search_index is not None
            and (time.monotonic() - self._index_built_at) < self.config.cache_ttl_seconds
        )

    async def build_search_index(self) -> list[SearchDocument]:
        if self._search_index_is_fresh():
            return self._search_index or []

        async with self._index_lock:
            if self._search_index_is_fresh():
                return self._search_index or []

            seed_urls = [self.config.base_url]
            for page in self._page_cache.values():
                if page.url not in seed_urls:
                    seed_urls.append(page.url)

            queue: deque[str] = deque(seed_urls)
            queued: set[str] = set(seed_urls)
            crawled_pages: list[DocumentationPage] = []
            seen_pages: set[str] = set()

            while queue and len(seen_pages) < self.config.max_pages:
                batch: list[str] = []
                while queue and len(batch) < self.config.concurrency and len(seen_pages) + len(batch) < self.config.max_pages:
                    batch.append(queue.popleft())

                results = await asyncio.gather(
                    *(self.fetch_page(url) for url in batch),
                    return_exceptions=True,
                )

                for result in results:
                    if isinstance(result, Exception):
                        continue
                    page = result
                    if page.url not in seen_pages:
                        seen_pages.add(page.url)
                        crawled_pages.append(page)
                    for link in page.links:
                        if link not in queued and link not in seen_pages and len(queued) < self.config.max_pages * 3:
                            queued.add(link)
                            queue.append(link)

            pages_for_index: dict[str, DocumentationPage] = {}
            for page in self._page_cache.values():
                pages_for_index[page.url] = page
            for page in crawled_pages:
                pages_for_index[page.url] = page

            self._search_index = [page_to_search_document(page) for page in pages_for_index.values()]
            self._index_built_at = time.monotonic()
            return self._search_index

    async def search(self, query: str, limit: int = 10) -> dict[str, object]:
        await self._enforce_rate_limit()
        validated_query = self._validate_query(query)
        validated_limit = self._validate_limit(limit, maximum=self.config.max_search_results)
        documents = await self.build_search_index()
        results = rank_documents(validated_query, documents, limit=validated_limit)
        return {
            "query": validated_query,
            "indexed_pages": len(documents),
            "results": [asdict(result) for result in results],
        }

    async def read_documentation(self, url: str) -> dict[str, object]:
        await self._enforce_rate_limit()
        page = await self.fetch_page(url)
        return {
            "title": sanitize_text(page.title, max_chars=240),
            "url": page.url,
            "summary": sanitize_text(page.summary, max_chars=600),
            "headings": [sanitize_text(heading, max_chars=240) for heading in page.headings],
            "markdown": sanitize_text(page.markdown, max_chars=self.config.max_document_chars),
        }

    async def read_sections(self, url: str, sections: list[str]) -> dict[str, object]:
        await self._enforce_rate_limit()
        validated_sections = self._validate_sections_input(sections)
        page = await self.fetch_page(url)
        normalized_targets = {normalize_heading(section): section for section in validated_sections}

        matched_sections: list[dict[str, object]] = []
        matched_normalized: set[str] = set()
        for section in page.sections:
            normalized_heading = normalize_heading(section.heading)
            for target_normalized, original in normalized_targets.items():
                if normalized_heading == target_normalized or target_normalized in normalized_heading:
                    matched_sections.append(
                        {
                            "requested": original,
                            "heading": sanitize_text(section.heading, max_chars=240),
                            "level": section.level,
                            "anchor": section.anchor,
                            "markdown": sanitize_text(section.markdown, max_chars=self.config.max_document_chars),
                        }
                    )
                    matched_normalized.add(target_normalized)
                    break

        missing = [original for normalized, original in normalized_targets.items() if normalized not in matched_normalized]
        return {
            "title": sanitize_text(page.title, max_chars=240),
            "url": page.url,
            "matched_sections": matched_sections,
            "missing_sections": missing,
        }

    async def list_documentation_pages(self, section: str | None = None, limit: int = 100) -> dict[str, object]:
        await self._enforce_rate_limit()
        validated_limit = self._validate_limit(limit, maximum=self.config.max_list_results)
        documents = await self.build_search_index()
        section_filter = collapse_whitespace(section or "").lower()
        if len(section_filter) > self.config.max_query_length:
            raise ValueError(f"section must be at most {self.config.max_query_length} characters")
        pages = []
        for document in documents:
            if section_filter and section_filter not in document.title_lower and section_filter not in document.path:
                continue
            pages.append(
                {
                    "title": sanitize_text(document.title, max_chars=240),
                    "url": document.url,
                    "summary": sanitize_text(document.summary, max_chars=600),
                }
            )
        pages.sort(key=lambda item: (item["title"].lower(), item["url"]))
        return {
            "total_pages": len(documents),
            "returned_pages": len(pages[:validated_limit]),
            "pages": pages[:validated_limit],
        }

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
