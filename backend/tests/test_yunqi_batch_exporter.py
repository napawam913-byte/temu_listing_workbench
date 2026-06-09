from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.modules.yunqi.batch_exporter import (
    export_yunqi_all_categories,
    list_yunqi_leaf_categories,
    rename_export_for_category,
)
from app.modules.yunqi.filter_configs import write_yunqi_category_filter_config
from app.modules.yunqi.export_files import rename_export_for_filter_config
from app.modules.yunqi.rpa_exporter import (
    ResponseDownload,
    parse_yunqi_export_record_time,
    save_download,
    select_yunqi_export_download_record,
)


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
        self.assertEqual(payload["export_modal"]["timeout_ms"], 300000)
        self.assertEqual(payload["export_modal"]["timestamp_tolerance_seconds"], 5)

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

    def test_selects_only_timestamped_export_record_after_request(self) -> None:
        requested_at = datetime(2026, 6, 5, 10, 53, 30)
        records = [
            {
                "index": 0,
                "fingerprint": "2026-06-05 10:48:50 下载",
                "time_text": "2026-06-05 10:48:50",
                "has_download": True,
            },
            {
                "index": 1,
                "fingerprint": "下载",
                "time_text": "",
                "has_download": True,
            },
            {
                "index": 2,
                "fingerprint": "2026-06-05 10:53:38 下载",
                "time_text": "2026-06-05 10:53:38",
                "has_download": True,
            },
        ]

        selected, rejected = select_yunqi_export_download_record(
            records,
            previous_records={"2026-06-05 10:48:50 下载"},
            requested_at=requested_at,
            timestamp_tolerance_seconds=5,
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["time_text"], "2026-06-05 10:53:38")
        self.assertEqual(parse_yunqi_export_record_time(selected["time_text"]), datetime(2026, 6, 5, 10, 53, 38))
        self.assertEqual(
            [item["reason"] for item in rejected],
            ["already_existed_before_export", "missing_or_unparseable_timestamp"],
        )

    def test_refuses_download_record_without_current_export_timestamp(self) -> None:
        selected, rejected = select_yunqi_export_download_record(
            [
                {
                    "index": 0,
                    "fingerprint": "2026-06-05 10:48:50 下载",
                    "time_text": "2026-06-05 10:48:50",
                    "has_download": True,
                },
                {
                    "index": 1,
                    "fingerprint": "下载",
                    "time_text": "",
                    "has_download": True,
                },
            ],
            previous_records=set(),
            requested_at=datetime(2026, 6, 5, 10, 53, 30),
            timestamp_tolerance_seconds=5,
        )

        self.assertIsNone(selected)
        self.assertEqual(
            [item["reason"] for item in rejected],
            ["timestamp_before_current_export", "missing_or_unparseable_timestamp"],
        )

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
        first_download = manifest["downloads"][0]
        self.assertEqual(first_download["status"], "exported")
        self.assertIn("Sports & Outdoors", Path(first_download["download_path"]).name)
        self.assertIn("Camping & Hiking", Path(first_download["download_path"]).name)
        self.assertRegex(Path(first_download["download_path"]).name, r"_20\d{2}-\d{2}-\d{2}\.csv$")
        self.assertEqual(Path(first_download["original_download_path"]).name, "leaf-1.csv")

    def test_renames_export_file_with_category_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "raw-yunqi-download.xlsx"
            source_path.write_bytes(b"PK\x03\x04fake-xlsx-content")

            renamed_path = rename_export_for_category(
                source_path,
                category_path=["Sports & Outdoors", "Camping & Hiking"],
                path_text="Sports & Outdoors > Camping & Hiking",
                date_text="2026-06-05",
            )

            self.assertEqual(renamed_path.name, "Sports & Outdoors__Camping & Hiking_2026-06-05.xlsx")
            self.assertTrue(renamed_path.exists())
            self.assertFalse(source_path.exists())
            self.assertEqual(renamed_path.read_bytes(), b"PK\x03\x04fake-xlsx-content")

    def test_renames_export_file_from_filter_config_category_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "20260605_102546_2062716458324344834.xlsx"
            source_path.write_bytes(b"PK\x03\x04fake-xlsx-content")

            renamed_path = rename_export_for_filter_config(
                source_path,
                {
                    "category_actions": [
                        {
                            "type": "cascader_path",
                            "path": ["Sports & Outdoors", "Pool & Spa"],
                        }
                    ]
                },
                date_text="2026-06-05",
            )

            self.assertEqual(renamed_path.name, "Sports & Outdoors__Pool & Spa_2026-06-05.xlsx")
            self.assertTrue(renamed_path.exists())
            self.assertFalse(source_path.exists())

    def test_renames_csv_export_and_removes_original_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "20260605_105338_raw_download.csv"
            source_path.write_text("商品ID,商品标题（中文）\n1,测试商品\n", encoding="utf-8")

            renamed_path = rename_export_for_filter_config(
                source_path,
                {
                    "category_actions": [
                        {
                            "type": "cascader_path",
                            "path": ["Pet Supplies", "Birds"],
                        }
                    ]
                },
                date_text="2026-06-05",
            )

            self.assertEqual(renamed_path.name, "Pet Supplies__Birds_2026-06-05.csv")
            self.assertTrue(renamed_path.exists())
            self.assertFalse(source_path.exists())
            self.assertEqual(list(Path(tmpdir).glob("20260605_105338_raw_download*.csv")), [])

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
            self.assertEqual(list(Path(tmpdir).glob("*.csv")), [])


if __name__ == "__main__":
    unittest.main()
