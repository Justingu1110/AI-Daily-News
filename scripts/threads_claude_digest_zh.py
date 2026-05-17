#!/usr/bin/env python3
"""
Threads Claude AI Digest Generator (Traditional Chinese)

Searches Threads for popular Claude/Anthropic posts via:
  1. Official Threads Graph API (keyword search) — requires user access token
  2. Web search fallback via SerpAPI / Google Custom Search — no Threads auth needed

Generates a Traditional Chinese digest using the Claude API.

Required environment variables:
  ANTHROPIC_API_KEY          - Anthropic API key for translation

For Threads API (recommended):
  THREADS_ACCESS_TOKEN       - Long-lived Threads user access token
                               (get at developers.facebook.com/docs/threads)

For web-search fallback (at least one required if no Threads token):
  SERPAPI_KEY                - SerpAPI key  (https://serpapi.com)
  GOOGLE_CSE_KEY             - Google Custom Search API key
  GOOGLE_CSE_ID              - Google Custom Search Engine ID
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import requests
import anthropic


# ── Threads API ──────────────────────────────────────────────────────────────

THREADS_API_BASE = "https://graph.threads.net/v1.0"

THREADS_KEYWORDS = [
    "Claude AI",
    "Anthropic",
    "Claude Code",
    "Claude Opus",
    "Claude Sonnet",
]

THREADS_FIELDS = "id,text,timestamp,username,like_count,reply_count,views,media_url,permalink"

# Accounts to always include even without keyword match
THREADS_KEY_ACCOUNTS = [
    "claudeai",       # official Anthropic account
    "anthropic",
]

MAX_POSTS_PER_KEYWORD = 10


def fetch_threads_keyword(token: str, keyword: str, search_type: str = "TOP") -> list[dict]:
    """Call the Threads keyword search endpoint."""
    params = {
        "q": keyword,
        "type": search_type,          # TOP or RECENT
        "fields": THREADS_FIELDS,
        "access_token": token,
    }
    url = f"{THREADS_API_BASE}/threads/keyword_search"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


def fetch_account_threads(token: str, username: str, limit: int = 10) -> list[dict]:
    """Fetch recent posts from a specific Threads account."""
    # First resolve username -> user ID
    id_resp = requests.get(
        f"{THREADS_API_BASE}/threads_discovery",
        params={"username": username, "access_token": token, "fields": "id,username"},
        timeout=15,
    )
    if id_resp.status_code != 200:
        return []
    user_id = id_resp.json().get("id")
    if not user_id:
        return []

    posts_resp = requests.get(
        f"{THREADS_API_BASE}/{user_id}/threads",
        params={
            "fields": THREADS_FIELDS,
            "limit": limit,
            "access_token": token,
        },
        timeout=15,
    )
    if posts_resp.status_code != 200:
        return []
    return posts_resp.json().get("data", [])


def collect_via_threads_api(token: str) -> list[dict]:
    seen_ids: set[str] = set()
    posts: list[dict] = []

    for keyword in THREADS_KEYWORDS:
        try:
            results = fetch_threads_keyword(token, keyword)
            for post in results[:MAX_POSTS_PER_KEYWORD]:
                if post.get("id") in seen_ids:
                    continue
                seen_ids.add(post["id"])
                posts.append(_normalise_threads_post(post))
            time.sleep(0.3)
        except Exception as exc:
            print(f"Warning: Threads API keyword search failed for {keyword!r}: {exc}")

    for account in THREADS_KEY_ACCOUNTS:
        try:
            for post in fetch_account_threads(token, account, limit=10):
                if post.get("id") in seen_ids:
                    continue
                seen_ids.add(post["id"])
                posts.append(_normalise_threads_post(post))
        except Exception as exc:
            print(f"Warning: account fetch failed for @{account}: {exc}")

    return _sort_and_trim(posts)


def _normalise_threads_post(post: dict) -> dict:
    return {
        "id": post.get("id", ""),
        "username": post.get("username", ""),
        "text": (post.get("text") or "")[:800],
        "timestamp": post.get("timestamp", ""),
        "like_count": post.get("like_count", 0),
        "reply_count": post.get("reply_count", 0),
        "views": post.get("views", 0),
        "permalink": post.get("permalink") or f"https://www.threads.com/@{post.get('username', '')}",
        "source": "threads_api",
    }


# ── SerpAPI / Google CSE fallback ────────────────────────────────────────────

SEARCH_QUERIES = [
    'site:threads.net OR site:threads.com "Claude" OR "Anthropic" AI 2026',
    'site:threads.com "@claudeai" OR "@anthropic" 2026',
    '"threads.com" Claude Anthropic 2026 post',
]


def collect_via_serpapi(serpapi_key: str) -> list[dict]:
    posts = []
    seen_urls: set[str] = set()

    for query in SEARCH_QUERIES:
        params = {
            "engine": "google",
            "q": query,
            "num": 10,
            "api_key": serpapi_key,
        }
        try:
            resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
            resp.raise_for_status()
            results = resp.json().get("organic_results", [])
            for r in results:
                url = r.get("link", "")
                if url in seen_urls:
                    continue
                if "threads.net" not in url and "threads.com" not in url:
                    continue
                seen_urls.add(url)
                posts.append(_normalise_search_result(r))
        except Exception as exc:
            print(f"Warning: SerpAPI search failed: {exc}")
        time.sleep(0.5)

    return posts


def collect_via_google_cse(api_key: str, cse_id: str) -> list[dict]:
    posts = []
    seen_urls: set[str] = set()

    for query in SEARCH_QUERIES:
        params = {
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": 10,
        }
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                url = item.get("link", "")
                if url in seen_urls:
                    continue
                if "threads.net" not in url and "threads.com" not in url:
                    continue
                seen_urls.add(url)
                posts.append(_normalise_search_result(item))
        except Exception as exc:
            print(f"Warning: Google CSE search failed: {exc}")
        time.sleep(0.5)

    return posts


def _normalise_search_result(item: dict) -> dict:
    snippet = item.get("snippet") or item.get("description") or ""
    title = item.get("title") or ""
    url = item.get("link") or item.get("url") or ""

    # Extract @username from threads URL
    username = ""
    parts = url.split("/@")
    if len(parts) > 1:
        username = parts[1].split("/")[0]

    return {
        "id": url,
        "username": username,
        "text": f"{title}\n{snippet}".strip()[:800],
        "timestamp": "",
        "like_count": 0,
        "reply_count": 0,
        "views": 0,
        "permalink": url,
        "source": "web_search",
    }


def _sort_and_trim(posts: list[dict], limit: int = 20) -> list[dict]:
    posts.sort(key=lambda p: (p.get("like_count", 0) + p.get("views", 0) * 0.01), reverse=True)
    return posts[:limit]


# ── Claude translation ────────────────────────────────────────────────────────

def translate_to_chinese(client: anthropic.Anthropic, posts: list[dict], target_date: str) -> str:
    posts_json = json.dumps(posts, ensure_ascii=False, indent=2)

    prompt = f"""你是一個 AI 新聞繁體中文編輯，專門整理 Threads 平台上關於 Claude AI 和 Anthropic 的熱門貼文。

以下是 {target_date} 從 Threads 抓取或搜尋到的貼文資料（JSON 格式）：

{posts_json}

請整理成繁體中文的每日摘要，格式如下：

## 熱門貼文

每則貼文包含：
- **帳號**（@username）
- **Threads 連結**
- **貼文內容摘要**（繁體中文，說明主要內容）
- **互動數據**（有的話列出 like、留言、瀏覽數；沒有則標注「平台限制，無法取得」）
- **重要性說明**：為什麼這則貼文值得關注？

## 今日重點

3~5 個要點，總結今天 Threads 上 Claude/Anthropic 最值得注意的趨勢。

請注意：
- 若貼文來自官方帳號（@claudeai, @anthropic），請特別標注「官方」
- 若互動數據為 0 或空白，說明「平台限制，互動數據無法取得」
- 直接輸出 Markdown，不需額外說明"""

    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── Digest builder & saver ────────────────────────────────────────────────────

def build_digest(translated: str, target_date: str, post_count: int, source: str) -> str:
    taipei_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    source_note = {
        "threads_api": "Threads Graph API（官方）",
        "web_search": "Google 搜尋引擎索引（Threads 無公開 API 的備用方案）",
        "mixed": "Threads Graph API + 搜尋引擎索引",
    }.get(source, source)

    header = f"""# Threads Claude AI 每日摘要（繁體中文）- {target_date}

**生成時間：** {taipei_time}（台北時間）
**資料來源：** Threads（threads.net / threads.com）
**抓取方式：** {source_note}
**涵蓋貼文數：** {post_count}

> **注意：** Threads 平台對自動化存取有嚴格限制。
> 使用官方 API 需要長效存取令牌（Long-Lived Access Token）；
> 備用的搜尋引擎方案僅能取得被索引的公開貼文，互動數據不可用。

---

"""
    return header + translated


def save_digest(content: str, target_date: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{target_date}-zh.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Threads Claude AI digest in Traditional Chinese")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: today Taipei time)")
    parser.add_argument("--output-dir", default="daily-digest/threads", help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Fetch posts without calling Claude API")
    args = parser.parse_args()

    taipei_tz = timezone(timedelta(hours=8))
    target_date = args.date or datetime.now(taipei_tz).strftime("%Y-%m-%d")

    print(f"Generating Threads Claude AI digest for {target_date}...")

    posts: list[dict] = []
    data_source = "web_search"

    # 1. Try official Threads API
    threads_token = os.environ.get("THREADS_ACCESS_TOKEN")
    if threads_token:
        print("Using Threads Graph API...")
        try:
            posts = collect_via_threads_api(threads_token)
            data_source = "threads_api"
            print(f"Fetched {len(posts)} posts via Threads API")
        except Exception as exc:
            print(f"Threads API failed: {exc}. Falling back to web search...")

    # 2. Fallback: SerpAPI
    if not posts:
        serpapi_key = os.environ.get("SERPAPI_KEY")
        if serpapi_key:
            print("Using SerpAPI fallback...")
            posts = collect_via_serpapi(serpapi_key)
            print(f"Found {len(posts)} posts via SerpAPI")

    # 3. Fallback: Google CSE
    if not posts:
        gkey = os.environ.get("GOOGLE_CSE_KEY")
        gcse = os.environ.get("GOOGLE_CSE_ID")
        if gkey and gcse:
            print("Using Google CSE fallback...")
            posts = collect_via_google_cse(gkey, gcse)
            print(f"Found {len(posts)} posts via Google CSE")

    if not posts:
        print("No posts found from any source. Exiting.")
        sys.exit(1)

    if args.dry_run:
        print(json.dumps(posts, ensure_ascii=False, indent=2))
        return

    anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    translated = translate_to_chinese(anthropic_client, posts, target_date)
    digest = build_digest(translated, target_date, len(posts), data_source)

    filepath = save_digest(digest, target_date, args.output_dir)
    print(f"Digest saved to: {filepath}")


if __name__ == "__main__":
    main()
