"""Tests for FeedWatcherTool."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools.feed_watcher import FeedWatcherTool


RSS_SAMPLE = """<?xml version="1.0"?>
<rss><channel><title>Test Feed</title>
<item><title>Item One</title><link>https://example.com/1</link><guid>a1</guid><description>First item</description></item>
<item><title>Item Two</title><link>https://example.com/2</link><guid>a2</guid><description>Second item</description></item>
</channel></rss>
"""


class TestFeedWatcherTool:
    def test_add_and_list(self, tmp_path):
        tool = FeedWatcherTool(context={"data_dir": str(tmp_path)})
        result = tool.execute(action="add", url="https://example.com/feed.xml")
        assert result.success
        listed = tool.execute(action="list")
        assert listed.success
        assert "example.com/feed.xml" in listed.output

    def test_scan_feed_collects_items(self, tmp_path):
        tool = FeedWatcherTool(context={"data_dir": str(tmp_path)})
        tool.execute(action="add", url="https://example.com/feed.xml")
        tool._fetch_url = lambda url: RSS_SAMPLE
        result = tool.execute(action="scan")
        assert result.success
        assert result.data["new_items"] == 2

    def test_items_and_mark_read(self, tmp_path):
        tool = FeedWatcherTool(context={"data_dir": str(tmp_path)})
        tool.execute(action="add", url="https://example.com/feed.xml")
        tool._fetch_url = lambda url: RSS_SAMPLE
        tool.execute(action="scan")
        items = tool.execute(action="items")
        assert items.success
        item_id = items.data["items"][0]["id"]
        marked = tool.execute(action="mark_read", item_id=item_id)
        assert marked.success

    def test_remove(self, tmp_path):
        tool = FeedWatcherTool(context={"data_dir": str(tmp_path)})
        tool.execute(action="add", url="https://example.com/feed.xml")
        removed = tool.execute(action="remove", url="https://example.com/feed.xml")
        assert removed.success
