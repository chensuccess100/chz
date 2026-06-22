import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_digest import (  # noqa: E402
    Article,
    clean_title,
    normalize_title,
    parse_feed,
    select_articles,
    title_matches_category,
)


RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>AI research milestone - Reuters</title>
    <link>https://example.com/a</link>
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

    def test_category_filter_rejects_unrelated_reuters_story(self):
        self.assertFalse(title_matches_category("Police seize cocaine shipment", "AI"))
        self.assertTrue(title_matches_category("New AI model improves protein design", "AI"))

    def test_category_filter_rejects_non_news_pages(self):
        self.assertFalse(title_matches_category("Senior Scientist job with Research Institute", "科学"))
        self.assertFalse(title_matches_category("New Jersey", "娱乐"))


if __name__ == "__main__":
    unittest.main()
