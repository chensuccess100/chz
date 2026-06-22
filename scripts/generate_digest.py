#!/usr/bin/env python3
"""Generate a Chinese daily news digest from public Google News RSS feeds."""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo


CHINA_TZ = ZoneInfo("Asia/Shanghai")
USER_AGENT = "daily-news-briefing/1.0 (+GitHub Actions)"

CATEGORIES = {
    "政治": [
        "site:reuters.com world politics war election diplomacy",
        "site:apnews.com world politics conflict election diplomacy",
    ],
    "AI": [
        "site:openai.com OR site:anthropic.com OR site:blog.google artificial intelligence",
        "site:reuters.com artificial intelligence regulation model launch",
        "site:technologyreview.com OR site:science.org artificial intelligence research",
    ],
    "娱乐": [
        "site:apnews.com entertainment film television music",
        "site:deadline.com box office awards film television",
        "site:billboard.com music entertainment",
    ],
    "科学": [
        "site:nature.com research discovery",
        "site:science.org research discovery",
        "site:nasa.gov science discovery mission",
    ],
}

CATEGORY_KEYWORDS = {
    "政治": {
        "politics", "political", "election", "government", "president", "minister",
        "diplomacy", "diplomatic", "war", "iran", "ukraine", "russia", "china",
        "trump", "g7", "nato", "parliament", "congress",
    },
    "AI": {
        "ai", "artificial intelligence", "openai", "anthropic", "deepmind", "chatgpt",
        "gemini", "machine learning", "language model", "neural", "robot", "人工智能",
        "大模型", "机器人",
    },
    "娱乐": {
        "film", "movie", "music", "actor", "actress", "television", "tv", "streaming",
        "box office", "award", "concert", "album", "festival", "broadway", "hollywood",
        "电影", "音乐", "票房", "电视剧",
    },
    "科学": {
        "science", "research", "discovery", "nasa", "telescope", "space", "genome",
        "cell", "climate", "physics", "biology", "medicine", "medical", "quantum",
        "asteroid", "planet", "material", "科学", "研究", "太空", "医学", "物理",
    },
}

SOURCE_WEIGHTS = {
    "路透": 30,
    "reuters": 30,
    "美联社": 28,
    "ap news": 28,
    "bbc": 26,
    "新华社": 26,
    "nature": 28,
    "science": 28,
    "nasa": 28,
    "中国科学院": 27,
    "科学网": 22,
    "财新": 24,
    "界面新闻": 18,
    "澎湃新闻": 18,
    "央视新闻": 22,
    "mit technology review": 26,
    "deadline": 22,
    "billboard": 22,
}

REJECT_TITLE_PATTERNS = {
    "job with",
    "jobs with",
    "top news stories today",
    "database lookup",
    "career opportunity",
}


@dataclass(frozen=True)
class Article:
    title: str
    link: str
    source: str
    published: datetime


def build_feed_url(query: str, hours: int) -> str:
    days = max(1, (hours + 23) // 24)
    search = f"{query} when:{days}d"
    params = urllib.parse.urlencode(
        {
            "q": search,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
    )
    return f"https://news.google.com/rss/search?{params}"


def fetch_feed(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def clean_title(raw_title: str, source: str) -> str:
    title = html.unescape(raw_title).strip()
    suffix = f" - {source}" if source else ""
    if suffix and title.casefold().endswith(suffix.casefold()):
        title = title[: -len(suffix)].rstrip()
    return re.sub(r"\s+", " ", title)


def parse_feed(payload: bytes) -> list[Article]:
    root = ET.fromstring(payload)
    articles: list[Article] = []

    for item in root.findall("./channel/item"):
        source_node = item.find("source")
        source = (source_node.text or "未知来源").strip() if source_node is not None else "未知来源"
        title = clean_title(item.findtext("title", ""), source)
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        if not title or not link or not pub_date:
            continue

        try:
            published = parsedate_to_datetime(pub_date)
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)

        articles.append(Article(title, link, source, published.astimezone(timezone.utc)))

    return articles


def normalize_title(title: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", title.casefold())


def title_matches_category(title: str, category: str) -> bool:
    folded = title.casefold()
    if any(pattern in folded for pattern in REJECT_TITLE_PATTERNS):
        return False
    if not re.search(r"[\u4e00-\u9fff]", title) and len(title.split()) < 4:
        return False
    for keyword in CATEGORY_KEYWORDS[category]:
        if keyword == "ai":
            if re.search(r"\bai\b", folded):
                return True
        elif keyword in folded:
            return True
    return False


def authority_score(source: str) -> int:
    folded = source.casefold()
    return max((weight for name, weight in SOURCE_WEIGHTS.items() if name in folded), default=0)


def article_score(article: Article, now: datetime) -> float:
    age_hours = max(0.0, (now - article.published).total_seconds() / 3600)
    recency = max(0.0, 30.0 - age_hours)
    return authority_score(article.source) + recency


def select_articles(
    articles: list[Article], now: datetime, hours: int, limit: int
) -> list[Article]:
    cutoff = now - timedelta(hours=hours)
    unique: dict[str, Article] = {}

    for article in articles:
        if article.published < cutoff or article.published > now + timedelta(hours=1):
            continue
        key = normalize_title(article.title)
        if not key:
            continue
        current = unique.get(key)
        if current is None or article_score(article, now) > article_score(current, now):
            unique[key] = article

    return sorted(
        unique.values(),
        key=lambda article: (article_score(article, now), article.published),
        reverse=True,
    )[:limit]


def collect_category(category: str, queries: list[str], hours: int) -> tuple[list[Article], list[str]]:
    articles: list[Article] = []
    errors: list[str] = []
    for query in queries:
        try:
            fetched = parse_feed(fetch_feed(build_feed_url(query, hours)))
            articles.extend(article for article in fetched if title_matches_category(article.title, category))
        except Exception as exc:  # Continue when one public feed is temporarily unavailable.
            errors.append(f"{query}: {type(exc).__name__}")
    return articles, errors


def render_digest(
    selected: dict[str, list[Article]], generated_at: datetime, errors: list[str]
) -> str:
    date_text = generated_at.strftime("%Y-%m-%d")
    time_text = generated_at.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 每日资讯简报 | {date_text}",
        "",
        f"> 生成时间：{time_text}（北京时间）",
        "> 数据来源：Google News 公开RSS；分类说明为中文，新闻标题保留原始语言。",
        "> 本版本不使用AI或付费API。",
        "",
    ]

    for category, articles in selected.items():
        lines.extend([f"## {category}", ""])
        if not articles:
            lines.extend(["- 当前时间窗口内未获取到可靠条目。", ""])
            continue
        for article in articles:
            local_time = article.published.astimezone(CHINA_TZ).strftime("%m-%d %H:%M")
            lines.append(
                f"- [{article.title}]({article.link}) - {article.source} · {local_time}"
            )
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "说明：标题按来源可信度和发布时间排序。请点击原文核实细节；突发新闻可能继续变化。",
        ]
    )
    if errors:
        lines.append(f"本次有 {len(errors)} 个RSS查询暂时失败，其余来源已正常生成。")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("report.md"))
    parser.add_argument("--hours", type=int, default=30)
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    selected: dict[str, list[Article]] = {}
    all_errors: list[str] = []
    total = 0

    for category, queries in CATEGORIES.items():
        articles, errors = collect_category(category, queries, args.hours)
        chosen = select_articles(articles, now, args.hours, args.limit)
        selected[category] = chosen
        all_errors.extend(errors)
        total += len(chosen)

    if total == 0:
        print("No recent articles were available; refusing to publish an empty issue.", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_digest(selected, now.astimezone(CHINA_TZ), all_errors),
        encoding="utf-8",
    )
    print(f"Generated {args.output} with {total} articles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
