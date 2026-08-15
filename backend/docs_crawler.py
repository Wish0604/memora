"""
docs_crawler.py
Live crawler for docs.flytbase.com and releases.flytbase.com.

Strategy:
  1. Fetch the site's `llms.txt` manifest (a flat list of markdown page
     URLs — the emerging convention for LLM-friendly doc sites).
  2. Fetch each page's markdown, hash the content, and cache it on disk
     (content-addressed by URL) with a `last_fetched_at` timestamp.
  3. On query time, the retriever can call `ensure_fresh(url)` which
     re-fetches only if the cached copy is older than DOC_CACHE_TTL_SECONDS
     (or if force=True), and only overwrites the cache if the content hash
     actually changed — so downstream vector index rebuilds are cheap.
  4. Extracted DocPage / ReleaseNote nodes, plus best-effort Feature /
     Plan / Version entity extraction, are handed to graph_engine builders.

NOTE ON THIS SANDBOX: outbound network here is restricted to a fixed
allow-list of package registries and does not include flytbase.com, so
live fetches will fail with a network error in *this* execution
environment. The module is written to run in the target deployment
environment where that domain is reachable; `simulate=True` lets you
exercise the pipeline end-to-end here using representative fixture pages.
"""
from __future__ import annotations
import hashlib
import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import httpx

from config import (
    DOCS_BASE_URL, RELEASES_BASE_URL, DOCS_LLMS_TXT, RELEASES_LLMS_TXT,
    CACHE_DIR, DOC_CACHE_TTL_SECONDS, DOC_FETCH_TIMEOUT_SECONDS, DOC_MAX_PAGES,
    canonicalize_feature,
)

DOC_CACHE_DIR = CACHE_DIR / "docs"
DOC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST_PATH = CACHE_DIR / "docs_manifest.json"


@dataclass
class DocPage:
    url: str
    source: str  # "docs" | "releases"
    title: str
    content: str
    content_hash: str
    last_fetched_at: float
    canonical_features: list[str]


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _cache_path_for(url: str) -> Path:
    safe = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return DOC_CACHE_DIR / f"{safe}.json"


class DocsCrawler:
    def __init__(self, simulate: bool = False, fixtures: Optional[dict[str, str]] = None):
        """
        simulate: if True, skip real HTTP calls and use `fixtures`
                  (url -> markdown content) instead. Useful for environments
                  where docs.flytbase.com is not network-reachable.
        """
        self.simulate = simulate
        self.fixtures = fixtures or {}
        self.client = httpx.Client(timeout=DOC_FETCH_TIMEOUT_SECONDS, follow_redirects=True)

    # -- manifest parsing ---------------------------------------------------
    def _fetch_text(self, url: str) -> str:
        if self.simulate:
            if url not in self.fixtures:
                raise FileNotFoundError(f"No fixture registered for {url}")
            return self.fixtures[url]
        resp = self.client.get(url)
        resp.raise_for_status()
        return resp.text

    def fetch_manifest(self, llms_txt_url: str) -> list[str]:
        """llms.txt is expected to be a newline-delimited list of page URLs
        (optionally as markdown links `[title](url)` — both forms handled)."""
        text = self._fetch_text(llms_txt_url)
        urls = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.search(r"\((https?://[^\s)]+)\)", line)
            if m:
                urls.append(m.group(1))
            elif line.startswith("http"):
                urls.append(line.split()[0])
        return urls[:DOC_MAX_PAGES]

    # -- per-page fetch + cache ----------------------------------------------
    def _load_cached(self, url: str) -> Optional[DocPage]:
        p = _cache_path_for(url)
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        return DocPage(**d)

    def _save_cache(self, page: DocPage):
        _cache_path_for(page.url).write_text(json.dumps(asdict(page)), encoding="utf-8")

    def ensure_fresh(self, url: str, source: str, force: bool = False) -> DocPage:
        cached = self._load_cached(url)
        if cached and not force and (time.time() - cached.last_fetched_at) < DOC_CACHE_TTL_SECONDS:
            return cached

        content = self._fetch_text(url)
        new_hash = _hash(content)
        title = self._extract_title(content, url)
        features = self._extract_canonical_features(content)

        if cached and cached.content_hash == new_hash:
            # content unchanged — just bump the freshness timestamp
            cached.last_fetched_at = time.time()
            self._save_cache(cached)
            return cached

        page = DocPage(
            url=url, source=source, title=title, content=content,
            content_hash=new_hash, last_fetched_at=time.time(),
            canonical_features=features,
        )
        self._save_cache(page)
        return page

    @staticmethod
    def _extract_title(content: str, url: str) -> str:
        m = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
        return m.group(1).strip() if m else url.rsplit("/", 1)[-1]

    @staticmethod
    def _extract_canonical_features(content: str) -> list[str]:
        found = set()
        # Scan headings and bold labels for feature keyword hits
        for line in content.splitlines():
            key = canonicalize_feature(line)
            if key:
                found.add(key)
        return sorted(found)

    # -- top-level sync ----------------------------------------------------
    def sync_all(self, force: bool = False) -> list[DocPage]:
        pages: list[DocPage] = []
        for base_manifest, source in ((DOCS_LLMS_TXT, "docs"), (RELEASES_LLMS_TXT, "releases")):
            try:
                urls = self.fetch_manifest(base_manifest)
            except Exception as e:
                print(f"[docs_crawler] manifest fetch failed for {base_manifest}: {e}")
                continue
            for url in urls:
                try:
                    pages.append(self.ensure_fresh(url, source, force=force))
                except Exception as e:
                    print(f"[docs_crawler] page fetch failed for {url}: {e}")
        manifest_summary = {
            "synced_at": time.time(),
            "page_count": len(pages),
            "urls": [p.url for p in pages],
        }
        MANIFEST_PATH.write_text(json.dumps(manifest_summary, indent=2), encoding="utf-8")
        return pages


# ---------------------------------------------------------------------------
# Representative fixtures so the pipeline is runnable/testable without
# network access to flytbase.com. Replace `simulate=False` in production.
# ---------------------------------------------------------------------------
FIXTURE_DOCS_LLMS = f"""# FlytBase Docs
[Live Video Streaming]({DOCS_BASE_URL}/streaming/live-video)
[Offline Mission Caching]({DOCS_BASE_URL}/missions/offline-caching)
[Role-Based Access Control]({DOCS_BASE_URL}/platform/rbac)
"""

FIXTURE_RELEASES_LLMS = f"""# FlytBase Releases
[v3.4.0 Release Notes]({RELEASES_BASE_URL}/v3.4.0)
[v3.2.0 Release Notes]({RELEASES_BASE_URL}/v3.2.0)
"""

FIXTURE_PAGES = {
    f"{DOCS_BASE_URL}/streaming/live-video": (
        "# Live Video Streaming\n\n"
        "Live video streaming from docks and drones is supported on the "
        "**Enterprise** and **Business** plans. It is not available on the "
        "Starter plan. Supported since platform version 3.2.0.\n"
    ),
    f"{DOCS_BASE_URL}/missions/offline-caching": (
        "# Offline Mission Caching\n\n"
        "Offline mission caching allows missions to be queued locally at "
        "low-connectivity sites and synced once connectivity is restored. "
        "Available on all plans since version 3.0.0.\n"
    ),
    f"{DOCS_BASE_URL}/platform/rbac": (
        "# Role-Based Access Control\n\n"
        "Role-based dashboard widgets and permission tiers are configurable "
        "for Enterprise plan organizations.\n"
    ),
    f"{RELEASES_BASE_URL}/v3.4.0": (
        "# v3.4.0 Release Notes\n\n"
        "- Added role-based dashboard widgets for Enterprise plan orgs.\n"
        "- Improved offline mission caching sync reliability.\n"
    ),
    f"{RELEASES_BASE_URL}/v3.2.0": (
        "# v3.2.0 Release Notes\n\n"
        "- Live video streaming launched for Enterprise and Business plans.\n"
    ),
}


def get_simulated_crawler() -> DocsCrawler:
    fixtures = {DOCS_LLMS_TXT: FIXTURE_DOCS_LLMS, RELEASES_LLMS_TXT: FIXTURE_RELEASES_LLMS, **FIXTURE_PAGES}
    return DocsCrawler(simulate=True, fixtures=fixtures)


if __name__ == "__main__":
    crawler = get_simulated_crawler()
    pages = crawler.sync_all()
    for p in pages:
        print(f"[{p.source}] {p.title} -> {p.url} (features: {p.canonical_features})")
