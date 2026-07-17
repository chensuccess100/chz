import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_digest import (  # noqa: E402
    Article,
    clean_summary,
    clean_title,
    google_news_article_id,
    normalize_title,
    parse_feed,
    render_digest,
    select_articles,
    title_matches_category,
)
from send_email import build_message, parse_recipients  # noqa: E402


RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>AI research milestone - Reuters</title>
    <link>https://example.com/a</link>
    <description><![CDATA[AI research milestone shows a new system can help scientists screen candidate medicines faster.]]></description>
    <pubDate>Mon, 22 Jun 2026 10:00:00 GMT</pubDate>
    <source url="https://reuters.com">Reuters</source>
  </item>
</channel></rss>
"""


class DigestTests(unittest.TestCase):
    def test_parse_feed_and_remove_source_suffix(self):
        articles = parse_feed(RSS_FIXTURE)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "AI research milestone")
        self.assertEqual(articles[0].source, "Reuters")
        self.assertIn("candidate medicines", articles[0].summary)

    def test_normalize_title_ignores_punctuation(self):
        self.assertEqual(normalize_title("AI: New Model!"), "ainewmodel")

    def test_select_articles_deduplicates_and_prefers_authority(self):
        now = datetime(2026, 6, 22, 12, tzinfo=timezone.utc)
        articles = [
            Article("同一条新闻", "https://example.com/low", "Blog", now),
            Article("同一条新闻", "https://example.com/high", "Reuters", now),
        ]
        chosen = select_articles(articles, now, hours=30, limit=6)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].link, "https://example.com/high")

    def test_clean_title_unescapes_html(self):
        self.assertEqual(clean_title("Science &amp; Space - NASA", "NASA"), "Science & Space")

    def test_clean_summary_removes_html_and_repeated_title(self):
        summary = clean_summary(
            "<p>AI research milestone - <b>Scientists reported a useful result.</b></p>",
            "AI research milestone",
        )
        self.assertEqual(summary, "Scientists reported a useful result.")

    def test_google_news_article_id_extracts_rss_article_token(self):
        token = google_news_article_id("https://news.google.com/rss/articles/CBMiExample?oc=5")
        self.assertEqual(token, "CBMiExample")

    def test_category_filter_rejects_unrelated_reuters_story(self):
        self.assertFalse(title_matches_category("Police seize cocaine shipment", "AI"))
        self.assertTrue(title_matches_category("New AI model improves protein design", "AI"))

    def test_category_filter_rejects_non_news_pages(self):
        self.assertFalse(title_matches_category("Senior Scientist job with Research Institute", "科学"))
        self.assertFalse(title_matches_category("New Jersey", "娱乐"))

    def test_email_recipients_and_subject(self):
        recipients = parse_recipients("one@qq.com, two@qq.com")
        message = build_message("# 每日资讯简报 | 2026-06-22\n\n内容\n", "sender@qq.com", recipients)
        self.assertEqual(recipients, ["one@qq.com", "two@qq.com"])
        self.assertEqual(message["Subject"], "每日资讯简报 | 2026-06-22")
        self.assertEqual(message["To"], "one@qq.com, two@qq.com")

    def test_render_digest_includes_summary_and_source_link(self):
        generated_at = datetime(2026, 6, 22, 20, tzinfo=timezone.utc)
        article = Article(
            "AI research milestone",
            "https://example.com/a",
            "Reuters",
            generated_at,
            "Scientists reported a useful result readers can understand without opening the link.",
        )
        digest = render_digest({"AI": [article]}, generated_at, [])
        self.assertIn("### AI research milestone", digest)
        self.assertIn("- 要点：Scientists reported", digest)
        self.assertIn("- 原文：https://example.com/a", digest)


if __name__ == "__main__":
    unittest.main()
