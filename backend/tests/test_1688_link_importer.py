import unittest

from app.modules.sourcing_1688.link_importer import (
    build_product_from_1688_page,
    extract_offer_id,
    normalize_input_urls,
)


class Link1688ImporterTest(unittest.TestCase):
    def test_extracts_offer_id_from_detail_url(self):
        self.assertEqual(
            extract_offer_id("https://detail.1688.com/offer/123456789.html?spm=a"),
            "123456789",
        )

    def test_normalizes_and_deduplicates_urls(self):
        self.assertEqual(
            normalize_input_urls([
                "detail.1688.com/offer/123.html\nhttps://detail.1688.com/offer/123.html",
            ]),
            ["https://detail.1688.com/offer/123.html"],
        )

    def test_builds_product_from_meta_tags(self):
        page_html = """
        <html>
          <head>
            <meta property="og:title" content="测试 1688 商品">
            <meta property="og:image" content="https://cbu01.alicdn.com/img/ibank/test.jpg">
          </head>
          <body>{"price":"12.50"}</body>
        </html>
        """

        product = build_product_from_1688_page("https://detail.1688.com/offer/123456.html", page_html, 1)

        self.assertEqual(product["source_type"], "1688")
        self.assertEqual(product["source_product_id"], "123456")
        self.assertEqual(product["title"], "测试 1688 商品")
        self.assertEqual(product["price_usd"], 12.5)
        self.assertEqual(product["main_image_url"], "https://cbu01.alicdn.com/img/ibank/test.jpg")

    def test_builds_product_category_from_breadcrumb(self):
        page_html = """
        <html>
          <head><meta property="og:title" content="测试钥匙扣"></head>
          <body>
            <div class="breadcrumb">
              <a>首页</a> &gt; <a>饰品</a> &gt; <a>钥匙配饰</a>
            </div>
            {"price":"1.20"}
          </body>
        </html>
        """

        product = build_product_from_1688_page("https://detail.1688.com/offer/456789.html", page_html, 1)

        self.assertEqual(product["category_path"], "饰品/钥匙配饰")
        self.assertEqual(product["category_level1"], "饰品")
        self.assertEqual(product["category_level2"], "钥匙配饰")


if __name__ == "__main__":
    unittest.main()
