from __future__ import annotations

import unittest

from app.modules.yunqi.category_catalog import category_key_for_path, flatten_category_tree


class YunqiCategoryCatalogTest(unittest.TestCase):
    def test_flatten_category_tree_preserves_path_and_labels(self) -> None:
        tree = [
            {
                "label": "Sports & Outdoors(运动与户外)",
                "label_en": "Sports & Outdoors",
                "label_cn": "运动与户外",
                "level": 1,
                "path_text": "Sports & Outdoors(运动与户外)",
                "path": ["Sports & Outdoors(运动与户外)"],
                "has_children": True,
                "children": [
                    {
                        "label": "Camping & Hiking(野营登山)",
                        "label_en": "Camping & Hiking",
                        "label_cn": "野营登山",
                        "level": 2,
                        "path_text": "Sports & Outdoors(运动与户外) > Camping & Hiking(野营登山)",
                        "path": ["Sports & Outdoors(运动与户外)", "Camping & Hiking(野营登山)"],
                        "has_children": False,
                        "children": [],
                    }
                ],
            }
        ]

        rows = flatten_category_tree(tree)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["label_cn"], "野营登山")
        self.assertEqual(rows[1]["parent_path_text"], "Sports & Outdoors(运动与户外)")
        self.assertEqual(
            rows[1]["path_text"],
            "Sports & Outdoors(运动与户外) > Camping & Hiking(野营登山)",
        )
        self.assertEqual(rows[1]["parent_key"], rows[0]["category_key"])

    def test_category_key_for_path_is_stable(self) -> None:
        path = "Sports & Outdoors(运动与户外) > Camping & Hiking(野营登山)"

        self.assertEqual(category_key_for_path(path), category_key_for_path(path))
        self.assertEqual(category_key_for_path("  ".join(path.split())), category_key_for_path(path))


if __name__ == "__main__":
    unittest.main()
