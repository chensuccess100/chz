#!/usr/bin/env python3
"""Generate a Chinese daily news digest from public Google News RSS feeds."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    CHINA_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    CHINA_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
USER_AGENT = "daily-news-briefing/1.0 (+GitHub Actions)"
SUMMARY_MAX_CHARS = 320
SUMMARY_MIN_CHARS = 80
GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
GITHUB_MODELS_MODEL = os.environ.get("GITHUB_MODELS_MODEL", "openai/gpt-4.1")
LOW_VALUE_SUMMARIES = {
    "Comprehensive up-to-date news coverage, aggregated from sources all over the world by Google News.",
}

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
    summary: str = ""


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


def read_url_text(url: str, timeout: int = 12, max_bytes: int = 600_000) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        page = response.read(max_bytes).decode("utf-8", errors="replace")
    return page, content_type


def clean_title(raw_title: str, source: str) -> str:
    title = html.unescape(raw_title).strip()
    suffix = f" - {source}" if source else ""
    if suffix and title.casefold().endswith(suffix.casefold()):
        title = title[: -len(suffix)].rstrip()
    return re.sub(r"\s+", " ", title)


def clean_summary(raw_text: str, title: str = "") -> str:
    text = html.unescape(raw_text)
    text = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -\t\r\n")
    if title and text.casefold().startswith(title.casefold()):
        text = text[len(title):].strip(" -:\t\r\n")
    if len(text) > SUMMARY_MAX_CHARS:
        text = text[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:")
        text += "..."
    return text


def is_low_value_summary(summary: str) -> bool:
    normalized = re.sub(r"\s+", " ", summary).strip()
    if not normalized:
        return True
    return normalized in LOW_VALUE_SUMMARIES or normalized.casefold() in {
        item.casefold() for item in LOW_VALUE_SUMMARIES
    }


def extract_meta_content(page: str) -> str:
    patterns = [
        r'<meta[^>]+(?:name|property)=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']description["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, page, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def extract_paragraph_summary(page: str) -> str:
    paragraphs = re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", page)
    cleaned = [
        clean_summary(paragraph)
        for paragraph in paragraphs
    ]
    useful = [
        paragraph
        for paragraph in cleaned
        if len(paragraph) >= SUMMARY_MIN_CHARS
        and not re.search(r"\b(subscribe|newsletter|cookies?|advertisement|sign up)\b", paragraph, re.I)
    ]
    return " ".join(useful[:2])


def google_news_article_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname == "news.google.com" and len(parts) >= 2 and parts[-2] in {"articles", "read"}:
        return parts[-1]
    return ""


def get_google_decoding_params(article_id: str) -> tuple[str, str]:
    for prefix in ("articles", "rss/articles"):
        page, _ = read_url_text(f"https://news.google.com/{prefix}/{article_id}", timeout=12)
        match = re.search(
            r'<div[^>]+jscontroller[^>]+data-n-a-sg="([^"]+)"[^>]+data-n-a-ts="([^"]+)"',
            page,
            flags=re.IGNORECASE,
        )
        if match:
            return html.unescape(match.group(1)), html.unescape(match.group(2))
    return "", ""


def decode_google_news_url(url: str) -> str:
    article_id = google_news_article_id(url)
    if not article_id:
        return url

    try:
        signature, timestamp = get_google_decoding_params(article_id)
        if not signature or not timestamp:
            return url

        payload = [
            "Fbv4je",
            (
                '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
                f'null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
                f'"{article_id}",{timestamp},"{signature}"]'
            ),
        ]
        data = urllib.parse.urlencode({"f.req": json.dumps([[payload]])}).encode("utf-8")
        request = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": USER_AGENT,
            },
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            body = response.read(200_000).decode("utf-8", errors="replace")
        parsed = json.loads(body.split("\n\n", 1)[1])[:-2]
        decoded_url = json.loads(parsed[0][2])[1]
        return decoded_url or url
    except (IndexError, KeyError, TypeError, ValueError, urllib.error.URLError, TimeoutError):
        return url


def fetch_article_summary(article: Article, url: str | None = None, timeout: int = 12) -> str:
    url = url or decode_google_news_url(article.link)
    try:
        page, content_type = read_url_text(url, timeout=timeout)
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return article.summary
    except (urllib.error.URLError, TimeoutError, ValueError):
        return article.summary

    raw_summary = extract_meta_content(page) or extract_paragraph_summary(page)
    summary = clean_summary(raw_summary, article.title)
    if is_low_value_summary(summary):
        return article.summary
    return summary or article.summary


def parse_feed(payload: bytes) -> list[Article]:
    root = ET.fromstring(payload)
    articles: list[Article] = []

    for item in root.findall("./channel/item"):
        source_node = item.find("source")
        source = (source_node.text or "未知来源").strip() if source_node is not None else "未知来源"
        title = clean_title(item.findtext("title", ""), source)
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        summary = clean_summary(item.findtext("description", ""), title)
        if not title or not link or not pub_date:
            continue

        try:
            published = parsedate_to_datetime(pub_date)
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)

        articles.append(Article(title, link, source, published.astimezone(timezone.utc), summary))

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


def enrich_articles(articles: list[Article], fetch_web_summaries: bool = False) -> list[Article]:
    enriched: list[Article] = []
    for article in articles:
        link = article.link
        summary = article.summary
        if fetch_web_summaries:
            link = decode_google_news_url(article.link)
            summary = fetch_article_summary(article, link)
        if is_low_value_summary(summary):
            summary = ""
        enriched.append(Article(article.title, link, article.source, article.published, summary))
    return enriched


def summarize_articles_with_github_models(category: str, articles: list[Article]) -> list[Article]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token or not articles:
        return articles

    items = [
        {
            "index": index,
            "title": article.title,
            "source": article.source,
            "published": article.published.astimezone(CHINA_TZ).strftime("%Y-%m-%d %H:%M"),
            "summary": article.summary,
        }
        for index, article in enumerate(articles)
    ]
    prompt = (
        "请把下面新闻整理成中文邮件简报。每条输出一个 JSON 对象，字段为 index 和 summary。"
        "summary 用 2 句中文，第一句说明发生了什么，第二句说明影响或背景。"
        "只能基于给出的标题、来源、时间和摘要，不要编造数字、人名或细节；信息不足时说明“据标题显示”。"
        f"分类：{category}\n新闻：{json.dumps(items, ensure_ascii=False)}"
    )
    payload = {
        "model": GITHUB_MODELS_MODEL,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "你是严谨的中文新闻简报编辑，只输出 JSON 数组，不输出 Markdown。",
            },
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        GITHUB_MODELS_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            response_body = response.read(500_000).decode("utf-8", errors="replace")
        content = json.loads(response_body)["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
        summaries = json.loads(content)
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return articles

    by_index = {
        int(item["index"]): clean_summary(str(item["summary"]))
        for item in summaries
        if isinstance(item, dict) and "index" in item and "summary" in item
    }
    return [
        Article(
            article.title,
            article.link,
            article.source,
            article.published,
            by_index.get(index) or article.summary,
        )
        for index, article in enumerate(articles)
    ]


def render_digest(
    selected: dict[str, list[Article]], generated_at: datetime, errors: list[str]
) -> str:
    date_text = generated_at.strftime("%Y-%m-%d")
    time_text = generated_at.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 每日资讯简报 | {date_text}",
        "",
        f"> 生成时间：{time_text}（北京时间）",
        "> 数据来源：Google News 公开RSS；中文要点由 GitHub Models 根据标题、来源和摘要整理。",
        "> 邮件中已列出要点，原文链接仅用于需要核实细节时查看。",
        "",
    ]

    for category, articles in selected.items():
        lines.extend([f"## {category}", ""])
        if not articles:
            lines.extend(["- 当前时间窗口内未获取到可靠条目。", ""])
            continue
        for article in articles:
            local_time = article.published.astimezone(CHINA_TZ).strftime("%m-%d %H:%M")
            lines.append(f"### {article.title}")
            lines.append(f"- 来源：{article.source} · {local_time}")
            if article.summary:
                lines.append(f"- 要点：{article.summary}")
            else:
                lines.append("- 要点：该来源未提供可提取的公开摘要，请点开原文核实。")
            lines.append(f"- 原文：{article.link}")
            lines.append("")

    lines.extend(
        [
            "---",
            "",
            "说明：条目按来源可信度和发布时间排序；要点基于标题、公开摘要或正文片段整理，突发新闻可能继续变化。",
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
    parser.add_argument(
        "--fetch-web-summaries",
        action="store_true",
        help="Fetch public article pages for extra snippets. Slower and optional.",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    selected: dict[str, list[Article]] = {}
    all_errors: list[str] = []
    total = 0

    for category, queries in CATEGORIES.items():
        articles, errors = collect_category(category, queries, args.hours)
        chosen = select_articles(articles, now, args.hours, args.limit)
        enriched = enrich_articles(chosen, fetch_web_summaries=args.fetch_web_summaries)
        selected[category] = summarize_articles_with_github_models(category, enriched)
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
