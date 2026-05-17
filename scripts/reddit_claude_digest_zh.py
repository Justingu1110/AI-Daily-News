#!/usr/bin/env python3
"""
Reddit Claude AI Digest Generator (Traditional Chinese)

Searches Reddit for popular Claude/Anthropic posts and generates
a Traditional Chinese digest using the Claude API for translation.

Required environment variables:
  REDDIT_CLIENT_ID     - Reddit app client ID
  REDDIT_CLIENT_SECRET - Reddit app client secret
  REDDIT_USER_AGENT    - Reddit API user agent string
  ANTHROPIC_API_KEY    - Anthropic API key for translation
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta

import praw
import anthropic


SUBREDDITS = [
    "ClaudeAI",
    "ClaudeCode",
    "artificial",
    "MachineLearning",
    "LocalLLaMA",
]

SEARCH_QUERIES = [
    "Claude",
    "Anthropic",
    "Claude Code",
    "Claude Opus",
    "Claude Sonnet",
]

# Minimum score to include a post
MIN_SCORE = 50
# Maximum posts per subreddit
MAX_POSTS_PER_SUB = 10
# Time filter for Reddit search
TIME_FILTER = "day"  # hour, day, week, month, year, all


def get_reddit_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "claude-digest-bot/1.0"),
        read_only=True,
    )


def fetch_top_posts(reddit: praw.Reddit, target_date: datetime) -> list[dict]:
    """Fetch top Claude-related posts from target subreddits."""
    seen_ids = set()
    posts = []

    for subreddit_name in SUBREDDITS:
        subreddit = reddit.subreddit(subreddit_name)

        # Hot posts
        for post in subreddit.hot(limit=MAX_POSTS_PER_SUB):
            if post.id in seen_ids or post.score < MIN_SCORE:
                continue
            if not _is_claude_related(post.title, post.selftext):
                continue
            seen_ids.add(post.id)
            posts.append(_extract_post(post, subreddit_name))

        # Search by query within the subreddit
        for query in SEARCH_QUERIES:
            for post in subreddit.search(query, time_filter=TIME_FILTER, limit=MAX_POSTS_PER_SUB, sort="top"):
                if post.id in seen_ids or post.score < MIN_SCORE:
                    continue
                seen_ids.add(post.id)
                posts.append(_extract_post(post, subreddit_name))

    # Sort by score descending, keep top 15
    posts.sort(key=lambda p: p["score"], reverse=True)
    return posts[:15]


def _is_claude_related(title: str, body: str) -> bool:
    keywords = ["claude", "anthropic", "opus", "sonnet", "haiku", "claude code", "claude ai"]
    text = (title + " " + body).lower()
    return any(kw in text for kw in keywords)


def _extract_post(post, subreddit_name: str) -> dict:
    return {
        "id": post.id,
        "title": post.title,
        "subreddit": subreddit_name,
        "url": f"https://www.reddit.com{post.permalink}",
        "score": post.score,
        "num_comments": post.num_comments,
        "selftext": post.selftext[:800] if post.selftext else "",
        "author": str(post.author) if post.author else "[deleted]",
        "created_utc": post.created_utc,
    }


def translate_posts_to_chinese(client: anthropic.Anthropic, posts: list[dict], target_date: str) -> str:
    """Use Claude to translate and summarize the posts in Traditional Chinese."""
    posts_json = json.dumps(posts, ensure_ascii=False, indent=2)

    prompt = f"""你是一個 AI 新聞摘要編輯，專門整理 Reddit 上關於 Claude AI 和 Anthropic 的熱門討論。

以下是今天（{target_date}）從 Reddit 抓取的熱門貼文資料（JSON 格式）：

{posts_json}

請將這些貼文整理成繁體中文的每日摘要報告，格式如下：

1. 每則貼文包含：
   - 標題（翻譯成繁體中文，保留原文標題）
   - 所在的 Subreddit
   - Reddit 連結
   - 摘要（用繁體中文說明主要內容、社群反應、重要性）
   - 互動數據（upvote 數、留言數）

2. 按照熱度（upvote）排序

3. 在最後加上「今日重點」段落，用 3-5 個要點總結今天 Claude/Anthropic 社群最重要的話題

請直接輸出 Markdown 格式的摘要內容，不需要額外說明。"""

    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


def build_digest(translated_content: str, target_date: str, post_count: int) -> str:
    taipei_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    header = f"""# Reddit Claude AI 每日摘要（繁體中文）- {target_date}

**生成時間：** {taipei_time}（台北時間）
**資料來源：** {", ".join(f"r/{s}" for s in SUBREDDITS)}
**涵蓋貼文數：** {post_count}

---

"""
    return header + translated_content


def save_digest(content: str, target_date: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{target_date}-zh.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Generate Chinese Reddit Claude digest")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: today in Taipei time)")
    parser.add_argument("--output-dir", default="daily-digest/reddit", help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Fetch posts but do not call Claude API")
    args = parser.parse_args()

    taipei_tz = timezone(timedelta(hours=8))
    target_date = args.date or datetime.now(taipei_tz).strftime("%Y-%m-%d")
    target_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=taipei_tz)

    print(f"Generating Reddit Claude digest for {target_date}...")

    reddit = get_reddit_client()
    posts = fetch_top_posts(reddit, target_dt)
    print(f"Fetched {len(posts)} posts")

    if args.dry_run:
        print(json.dumps(posts, ensure_ascii=False, indent=2))
        return

    if not posts:
        print("No posts found, exiting.")
        sys.exit(1)

    anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    translated = translate_posts_to_chinese(anthropic_client, posts, target_date)
    digest = build_digest(translated, target_date, len(posts))

    filepath = save_digest(digest, target_date, args.output_dir)
    print(f"Digest saved to: {filepath}")


if __name__ == "__main__":
    main()
