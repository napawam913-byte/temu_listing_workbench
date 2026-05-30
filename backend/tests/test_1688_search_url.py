import unittest

from app.modules.sourcing_1688.search_url import build_1688_search_url, encode_1688_keyword


class Search1688UrlTest(unittest.TestCase):
    def test_encodes_chinese_keywords_with_gbk(self):
        self.assertEqual(encode_1688_keyword("龙虾扣"), "%C1%FA%CF%BA%BF%DB")

    def test_builds_1688_search_url(self):
        url = build_1688_search_url("龙虾扣 Y2K")

        self.assertEqual(url, "https://s.1688.com/selloffer/offer_search.htm?keywords=%C1%FA%CF%BA%BF%DB%20Y2K")

    def test_rejects_blank_keyword(self):
        with self.assertRaises(ValueError):
            build_1688_search_url("   ")


if __name__ == "__main__":
    unittest.main()
