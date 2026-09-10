import json
import os
import time
import unittest
from unittest.mock import Mock, patch

import requests

from instances.steam_auto import SteamAuto
from steam.SteamAPI import SteamAPI


class SteamNewsFetchTests(unittest.TestCase):
    def test_requests_full_news_content(self):
        api = SteamAPI("steam-key")
        response = Mock()
        response.json.return_value = {"appnews": {"newsitems": []}}
        api.session.get = Mock(return_value=response)

        api.get_steam_news(app_id=730, count=10)

        params = api.session.get.call_args.kwargs["params"]
        self.assertEqual(params["maxlength"], 0)


class SteamNewsTranslationTests(unittest.TestCase):
    def setUp(self):
        self.instance = SteamAuto.__new__(SteamAuto)

    @patch.dict(os.environ, {"DEEPSEEK_API_KEY": "deepseek-key"}, clear=False)
    @patch("instances.steam_auto.requests.post")
    def test_retries_translation_once_then_returns_chinese(self, post):
        success = Mock()
        success.json.return_value = {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({
                        "title": "更新说明",
                        "contents": "这是完整的中文正文。",
                    }, ensure_ascii=False)
                }
            }]
        }
        post.side_effect = [requests.Timeout("timeout"), success]

        result = self.instance._translate_cs2_news("Update Notes", "Full English body.")

        self.assertEqual(result, ("更新说明", "这是完整的中文正文。", True))
        self.assertEqual(post.call_count, 2)

    @patch.dict(os.environ, {"DEEPSEEK_API_KEY": "deepseek-key"}, clear=False)
    @patch("instances.steam_auto.requests.post")
    def test_falls_back_to_complete_english_after_two_failures(self, post):
        post.side_effect = requests.Timeout("timeout")

        result = self.instance._translate_cs2_news("Update Notes", "Full English body.")

        self.assertEqual(result, ("Update Notes", "Full English body.", False))
        self.assertEqual(post.call_count, 2)

    @patch.dict(os.environ, {"DEEPSEEK_API_KEY": "deepseek-key"}, clear=False)
    @patch("instances.steam_auto.requests.post")
    def test_retries_malformed_json_shape_then_falls_back_to_english(self, post):
        malformed = Mock()
        malformed.json.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": "[]"}}]
        }
        post.return_value = malformed

        result = self.instance._translate_cs2_news("Update Notes", "Full English body.")

        self.assertEqual(result, ("Update Notes", "Full English body.", False))
        self.assertEqual(post.call_count, 2)

    @patch.dict(os.environ, {"DEEPSEEK_API_KEY": "deepseek-key"}, clear=False)
    @patch("instances.steam_auto.requests.post")
    def test_incomplete_deepseek_response_is_retried_then_falls_back(self, post):
        incomplete = Mock()
        incomplete.json.return_value = {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": json.dumps({"title": "标题", "contents": "半段"})},
            }]
        }
        post.return_value = incomplete

        result = self.instance._translate_cs2_news("Update Notes", "Full English body.")

        self.assertEqual(result, ("Update Notes", "Full English body.", False))
        self.assertEqual(post.call_count, 2)

    @patch.dict(os.environ, {"DEEPSEEK_API_KEY": "deepseek-key"}, clear=False)
    @patch("instances.steam_auto.requests.post")
    def test_translates_long_body_in_segments_and_reassembles_all_output(self, post):
        first = Mock()
        first.json.return_value = {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({"title": "中文标题", "contents": "第一段\n"}, ensure_ascii=False)},
            }]
        }
        second = Mock()
        second.json.return_value = {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({"title": "中文标题", "contents": "第二段"}, ensure_ascii=False)},
            }]
        }
        post.side_effect = [first, second]
        body = ("A" * 4000) + "\n" + ("B" * 4000)

        result = self.instance._translate_cs2_news("Update Notes", body)

        self.assertEqual(result, ("中文标题", "第一段\n第二段", True))
        self.assertEqual(post.call_count, 2)

    def test_cleans_html_and_common_steam_bbcode_without_truncating(self):
        source = (
            '<p>Fixes &amp; changes</p><br>[b]Important[/b]: '
            '[url=https://example.com]details[/url]'
            '<ul><li><a href="https://html.example">HTML link</a></li></ul>'
            '[img]https://example.com/image.png[/img]'
        )

        result = self.instance._clean_cs2_news_contents(source)

        self.assertEqual(
            result,
            "Fixes & changes\n\nImportant: details (https://example.com)\n"
            "- HTML link (https://html.example)\n\n图片：https://example.com/image.png",
        )

    def test_splits_long_messages_without_losing_content(self):
        source = ("A" * 1200) + "\n" + ("B" * 1200) + "\n" + ("C" * 1200)

        chunks = self.instance._split_cs2_news_message(source, max_length=1800)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 1800 for chunk in chunks))
        self.assertEqual("".join(chunks), source)


class SteamNewsDeliveryTests(unittest.TestCase):
    def test_sends_translated_full_news_and_only_then_caches_gid(self):
        instance = SteamAuto.__new__(SteamAuto)
        instance.enable_news_check = True
        instance.cached_news_gids = {"old": time.time()}
        instance.steam = Mock()
        instance.steam.get_steam_news.return_value = [{
            "gid": "new",
            "title": "English title",
            "contents": "<p>Full English body.</p>",
            "url": "https://example.com/update",
        }]
        instance._clean_news_cache = Mock()
        instance._trim_news_cache = Mock()
        instance.save_news_cache = Mock()
        instance._translate_cs2_news = Mock(return_value=("中文标题", "完整中文正文。", True))
        sent = []
        instance.send_message = sent.append

        instance.check_cs2_news()

        instance._translate_cs2_news.assert_called_once_with("English title", "Full English body.")
        self.assertIn("中文标题", "".join(sent))
        self.assertIn("完整中文正文。", "".join(sent))
        self.assertNotIn("Full English body.", "".join(sent))
        self.assertIn("new", instance.cached_news_gids)
        instance.save_news_cache.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
