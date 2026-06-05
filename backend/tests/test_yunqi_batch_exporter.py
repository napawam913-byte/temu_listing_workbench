from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.modules.yunqi.batch_exporter import export_yunqi_all_categories, list_yunqi_leaf_categories
from app.modules.yunqi.filter_configs import write_yunqi_category_filter_config
from app.modules.yunqi.rpa_exporter import ResponseDownload, save_download


class YunqiBatchExporterTest(unittest.TestCase):
    def test_writes_category_filter_config_for_robot_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = write_yunqi_category_filter_config(
                category_key="cat-1",
                category_path=["Sports & Outdoors(运动与户外)", "Camping & Hiking(野营登山)"],
                path_text="Sports & Outdoors(运动与户外) > Camping & Hiking(野营登山)",
                output_dir=tmpdir,
            )

            payload = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["site_actions"][0]["label"], "国家")
        self.assertEqual(payload["site_actions"][0]["text"], "美国站")
        self.assertEqual(payload["category_actions"][0]["placeholder"], "分类筛选")
        self.assertEqual(
            payload["category_actions"][0]["path"],
            ["Sports & Outdoors(运动与户外)", "Camping & Hiking(野营登山)"],
        )
        self.assertEqual(payload["listing_date_actions"][0]["text"], "3月内")
        self.assertEqual(payload["export_modal"]["start_text"], "立即导出")
        self.assertEqual(payload["export_modal"]["download_text"], "下载")

    def test_lists_only_leaf_categories(self) -> None:
        rows = [
            {
                "id": "parent",
                "category_key": "parent",
                "label": "Sports & Outdoors(运动与户外)",
                "path_text": "Sports & Outdoors(运动与户外)",
                "path": ["Sports & Outdoors(运动与户外)"],
                "has_children": True,
            },
            {
                "id": "leaf",
                "category_key": "leaf",
                "label": "Camping & Hiking(野营登山)",
                "path_text": "Sports & Outdoors(运动与户外) > Camping & Hiking(野营登山)",
                "path": ["Sports & Outdoors(运动与户外)", "Camping & Hiking(野营登山)"],
                "has_children": False,
            },
        ]

        with patch("app.modules.yunqi.batch_exporter.list_yunqi_categories", return_value=rows):
            categories = list_yunqi_leaf_categories()

        self.assertEqual(len(categories), 1)
        self.assertEqual(categories[0]["category_key"], "leaf")

    def test_batch_export_polls_categories_and_writes_manifest(self) -> None:
        rows = [
            {
                "id": "leaf-1",
                "category_key": "leaf-1",
                "label": "Camping & Hiking(野营登山)",
                "path_text": "Sports & Outdoors(运动与户外) > Camping & Hiking(野营登山)",
                "path": ["Sports & Outdoors(运动与户外)", "Camping & Hiking(野营登山)"],
                "has_children": False,
            },
            {
                "id": "leaf-2",
                "category_key": "leaf-2",
                "label": "Pool & Spa(泳池和水疗)",
                "path_text": "Sports & Outdoors(运动与户外) > Pool & Spa(泳池和水疗)",
                "path": ["Sports & Outdoors(运动与户外)", "Pool & Spa(泳池和水疗)"],
                "has_children": False,
            },
        ]
        config_calls: list[dict[str, object]] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            def fake_write_config(**kwargs):
                config_calls.append(kwargs)
                path = tmp_path / f"{kwargs['category_key']}.json"
                path.write_text("{}", encoding="utf-8")
                return path

            def fake_export(**kwargs):
                filename = f"{Path(kwargs['filter_config_path']).stem}.csv"
                download_path = tmp_path / filename
                download_path.write_text("商品ID,商品标题（中文）\n", encoding="utf-8")
                return {
                    "status": "exported",
                    "download_path": str(download_path),
                    "suggested_filename": filename,
                }

            with (
                patch("app.modules.yunqi.batch_exporter.BATCH_RUN_DIR", tmp_path / "batch_runs"),
                patch("app.modules.yunqi.batch_exporter.init_db"),
                patch("app.modules.yunqi.batch_exporter.list_yunqi_categories", return_value=rows),
                patch("app.modules.yunqi.batch_exporter.write_yunqi_category_filter_config", side_effect=fake_write_config),
                patch("app.modules.yunqi.batch_exporter.export_yunqi_excel_via_rpa", side_effect=fake_export),
            ):
                result = export_yunqi_all_categories(delay_seconds=0)

            manifest_path = Path(result["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_exists = manifest_path.exists()

        self.assertEqual(len(config_calls), 2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["failed_count"], 0)
        self.assertTrue(manifest_exists)
        self.assertEqual(len(manifest["downloads"]), 2)
        self.assertEqual(manifest["downloads"][0]["status"], "exported")
        self.assertTrue(manifest["downloads"][0]["download_path"].endswith("leaf-1.csv"))

    def test_save_download_repairs_xlsx_content_named_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = save_download(
                ResponseDownload(
                    content=b"PK\x03\x04fake-xlsx-content",
                    suggested_filename="yunqi_export.csv",
                    url="https://example.com/yunqi_export.csv",
                ),
                Path(tmpdir),
            )

            self.assertEqual(saved_path.suffix, ".xlsx")
            self.assertTrue(saved_path.exists())
            self.assertEqual(saved_path.read_bytes(), b"PK\x03\x04fake-xlsx-content")


if __name__ == "__main__":
    unittest.main()
