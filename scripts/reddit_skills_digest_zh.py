#!/usr/bin/env python3
"""
Reddit Claude Code Skills Digest Generator (Traditional Chinese)

Searches Reddit for posts recommending Claude Code skills (SKILL.md),
extracts skill names / GitHub links, and generates a Traditional Chinese
digest using the Claude API for translation and summarisation.

Required environment variables:
  REDDIT_CLIENT_ID     - Reddit app client ID
  REDDIT_CLIENT_SECRET - Reddit app client secret
  REDDIT_USER_AGENT    - Reddit API user agent string
  ANTHROPIC_API_KEY    - Anthropic API key for summarisation
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone, timedelta

import praw
import anthropic


SUBREDDITS = [
    "ClaudeCode",
    "ClaudeAI",
    "artificial",
    "LocalLLaMA",
    "ChatGPTCoding",
]

SKILLS_SEARCH_QUERIES = [
    "skill recommend",
    "SKILL.md",
    "claude skill install",
    "best skills claude code",
    "slash command skill",
    "plugin marketplace",
    "superpowers obra",
    "awesome claude skills",
]

GITHUB_PATTERN = re.compile(r"https?://github\.com/[\w\-\.]+/[\w\-\.]+", re.IGNORECASE)

MIN_SCORE = 20
MAX_POSTS_PER_QUERY = 15
TIME_FILTER = "month"


def get_reddit_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "claude-skills-digest/1.0"),
        read_only=True,
    )


def fetch_skills_posts(reddit: praw.Reddit) -> list[dict]:
    seen_ids = set()
    posts = []

    for subreddit_name in SUBREDDITS:
        subreddit = reddit.subreddit(subreddit_name)
        for query in SKILLS_SEARCH_QUERIES:
            try:
                results = subreddit.search(
                    query,
                    time_filter=TIME_FILTER,
                    limit=MAX_POSTS_PER_QUERY,
                    sort="top",
                )
                for post in results:
                    if post.id in seen_ids or post.score < MIN_SCORE:
                        continue
                    if not _is_skills_related(post.title, post.selftext):
                        continue
                    seen_ids.add(post.id)
                    posts.append(_extract_post(post, subreddit_name))
            except Exception as exc:
                print(f"Warning: search failed for {subreddit_name!r}/{query!r}: {exc}")

    posts.sort(key=lambda p: p["score"], reverse=True)
    return posts[:25]


def _is_skills_related(title: str, body: str) -> bool:
    keywords = [
        "skill", "skill.md", "/plugin", "slash command", "claude code skill",
        "recommend", "superpowers", "obra", "awesome-claude", "agentskills",
    ]
    text = (title + " " + body).lower()
    return any(kw in text for kw in keywords)


def _extract_post(post, subreddit_name: str) -> dict:
    body = post.selftext or ""
    github_links = list(set(GITHUB_PATTERN.findall(body + " " + post.url)))
    return {
        "id": post.id,
        "title": post.title,
        "subreddit": subreddit_name,
        "url": f"https://www.reddit.com{post.permalink}",
        "score": post.score,
        "num_comments": post.num_comments,
        "body_excerpt": body[:600],
        "github_links": github_links[:5],
        "author": str(post.author) if post.author else "[deleted]",
    }


def summarise_skills_in_chinese(client: anthropic.Anthropic, posts: list[dict], target_date: str) -> str:
    posts_json = json.dumps(posts, ensure_ascii=False, indent=2)

    prompt = f"""你是一個 Claude Code 技術社群的繁體中文編輯。

以下是從 Reddit 抓取的、與「Claude Code Skills」相關的熱門貼文（JSON 格式，日期：{target_date}）：

{posts_json}

請整理出一份繁體中文的「Reddit 社群推薦 Skills 精選」報告，格式要求：

1. **Skills 推薦列表**（按 upvote 排序）
   每個 Skill 包含：
   - Skill 名稱（保留原文）
   - GitHub 連結（如有）
   - 一句話說明這個 Skill 的用途
   - Reddit 社群的評價或推薦理由（中文摘要）
   - 互動數據（upvote / 留言數）

2. **今日社群趨勢**：3~5 點，說明社群最近對哪類 Skill 最感興趣（例如：自動化、資安、設計等）

3. **新手推薦入門 Skills**：列出 3 個最適合新手安裝的 Skills（依社群共識）

請直接輸出 Markdown 格式，不要加額外說明。如果某篇貼文並未明確推薦具體 Skill，請跳過或只概述社群討論方向。"""

    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def build_digest(translated: str, target_date: str, post_count: int) -> str:
    taipei_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    header = f"""# Reddit 社群推薦 Claude Code Skills - {target_date}

**生成時間：** {taipei_time}（台北時間）
**資料來源：** {", ".join(f"r/{s}" for s in SUBREDDITS)}
**搜尋關鍵字：** skill, SKILL.md, plugin marketplace, recommend, superpowers…
**涵蓋貼文數：** {post_count}

---

"""
    return header + translated


def save_digest(content: str, target_date: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{target_date}-skills-zh.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Generate Chinese Reddit Claude Skills digest")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: today Taipei time)")
    parser.add_argument("--output-dir", default="daily-digest/reddit", help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Fetch posts without calling Claude API")
    args = parser.parse_args()

    taipei_tz = timezone(timedelta(hours=8))
    target_date = args.date or datetime.now(taipei_tz).strftime("%Y-%m-%d")

    print(f"Generating Reddit Claude Skills digest for {target_date}...")

    reddit = get_reddit_client()
    posts = fetch_skills_posts(reddit)
    print(f"Fetched {len(posts)} skill-related posts")

    if args.dry_run:
        print(json.dumps(posts, ensure_ascii=False, indent=2))
        return

    if not posts:
        print("No posts found, exiting.")
        sys.exit(1)

    anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    translated = summarise_skills_in_chinese(anthropic_client, posts, target_date)
    digest = build_digest(translated, target_date, len(posts))

    filepath = save_digest(digest, target_date, args.output_dir)
    print(f"Skills digest saved to: {filepath}")


if __name__ == "__main__":
    main()
