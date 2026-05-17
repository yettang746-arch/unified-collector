"""GitHub Trending crawler."""
import urllib.request
import json
import ssl
import certifi
from typing import List, Dict, Any

from .base import BaseCrawler

SSL_CTX = ssl.create_default_context(cafile=certifi.where())


class GitHubTrendingCrawler(BaseCrawler):
    """Crawl GitHub Trending repos via unofficial API or scrape."""

    def fetch(self) -> List[Dict[str, Any]]:
        language = self.config.get("language", "")
        # Use the unofficial GitHub Trending API
        url = "https://api.gitterapp.com/repositories"
        if language:
            url += f"?language={language}&since=daily"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            # Fallback: scrape GitHub trending page
            return self._scrape_github(language)

        items = []
        for repo in (data if isinstance(data, list) else data.get("items", data.get("repositories", [])))[:10]:
            name = repo.get("name") or repo.get("repo_name", "")
            author = repo.get("author", "")
            desc = repo.get("description", "") or ""
            stars = repo.get("stars", repo.get("currentPeriodStars", 0))
            url_repo = repo.get("url", f"https://github.com/{author}/{name}" if author and name else "")
            lang_list = repo.get("language", repo.get("programmingLanguage", ""))
            if not url_repo and author and name:
                url_repo = f"https://github.com/{author}/{name}"
            if name:
                title = f"{author}/{name}" if author else name
                if isinstance(stars, (int, float)) and stars > 0:
                    title += f" ⭐{stars}"
                items.append({
                    "title": title,
                    "url": url_repo,
                    "summary": desc[:300],
                    "published_at": "",
                    "tags": json.dumps([lang_list] if lang_list else []),
                    "raw_content": json.dumps({"stars": stars, "language": lang_list}),
                })
        return items

    def _scrape_github(self, language: str) -> List[Dict[str, Any]]:
        """Fallback: scrape GitHub trending page directly."""
        url = "https://github.com/trending"
        if language:
            url += f"/{language}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"  ERROR GitHub Trending {self.name}: {e}")
            return []

        # Parse HTML - simple regex approach
        items = []
        import re
        # Match repo rows: <h2 class="h3 lh-condensed"> ... <a href="/owner/repo">
        repo_pattern = re.compile(r'<h2[^>]*class="h3[^"]*"[^>]*>.*?<a[^>]*href="(/[^/]+/[^"]+)"[^>]*>\s*(.*?)\s*</a>', re.DOTALL)
        desc_pattern = re.compile(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>', re.DOTALL)

        repos = repo_pattern.findall(raw)
        descs = desc_pattern.findall(raw)

        for i, (path, name) in enumerate(repos[:10]):
            name = re.sub(r'\s+', ' ', name).strip()
            full_name = path.strip("/")
            desc = re.sub(r'<[^>]+>', '', descs[i]).strip()[:300] if i < len(descs) else ""
            items.append({
                "title": full_name,
                "url": f"https://github.com{path}",
                "summary": desc,
                "published_at": "",
                "tags": json.dumps([language] if language else []),
                "raw_content": "",
            })
        return items
