import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import database
from app.modules.visual_generation.service import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RETRY_WAITING,
    VISUAL_PROMPT_LOGIC_VERSION,
    build_visual_prompt_context,
    ensure_visual_generation_schema,
    mark_task_failed,
    mark_task_retry_waiting,
    run_visual_task_pipeline,
    visual_task_prompt_is_stale,
)
from app.modules.visual_generation.planner import build_mother_prompt_from_plan, build_product_analysis_instruction


class VisualGenerationSkuBindingTest(unittest.TestCase):
    def insert_visual_task(
        self,
        *,
        conn,
        task_id: str,
        user_id: str,
        tmpdir: str,
        status: str = TASK_STATUS_FAILED,
        prompt_text: str = "",
        mother_image_path: str = "",
        analysis_json: dict | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO visual_generation_tasks (
                id, user_id, link_record_id, product_id, mode, layout, requested_count,
                status, source_image_ref, record_json, analysis_json, prompt_text,
                mother_image_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                "",
                "product-1",
                "main-gallery",
                "3x3",
                9,
                status,
                "https://example.test/source.jpg",
                "{}",
                json.dumps(analysis_json or {}, ensure_ascii=False),
                prompt_text,
                mother_image_path,
                database.utc_now_text(),
                database.utc_now_text(),
            ),
        )

    def test_retry_with_existing_prompt_skips_planning_and_generates_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                task_id = "visual-prompt-ready"
                user_id = "user-1"
                with database.get_connection() as conn:
                    ensure_visual_generation_schema(conn)
                    self.insert_visual_task(
                        conn=conn,
                        task_id=task_id,
                        user_id=user_id,
                        tmpdir=tmpdir,
                        prompt_text="ready mother prompt",
                        analysis_json={"visualPromptLogicVersion": VISUAL_PROMPT_LOGIC_VERSION},
                    )

                with patch("app.modules.visual_generation.service.plan_visual_task") as plan_task:
                    with patch("app.modules.visual_generation.service.generate_visual_task", return_value={"id": task_id}) as generate_task:
                        run_visual_task_pipeline(
                            task_id=task_id,
                            user_id=user_id,
                            apply_to_link_record=False,
                            reuse_existing_outputs=True,
                        )

                plan_task.assert_not_called()
                generate_task.assert_called_once()
            finally:
                database.DATABASE_PATH = original_path

    def test_retry_with_existing_mother_image_skips_image_generation_and_splits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                task_id = "visual-mother-ready"
                user_id = "user-1"
                mother_path = str(Path(tmpdir) / "mother.png")
                Path(mother_path).write_bytes(b"fake image bytes")
                with database.get_connection() as conn:
                    ensure_visual_generation_schema(conn)
                    self.insert_visual_task(
                        conn=conn,
                        task_id=task_id,
                        user_id=user_id,
                        tmpdir=tmpdir,
                        prompt_text="ready mother prompt",
                        mother_image_path=mother_path,
                        analysis_json={"visualPromptLogicVersion": VISUAL_PROMPT_LOGIC_VERSION},
                    )

                with patch("app.modules.visual_generation.service.plan_visual_task") as plan_task:
                    with patch("app.modules.visual_generation.service.generate_visual_task") as generate_task:
                        with patch("app.modules.visual_generation.service.split_visual_task", return_value={"id": task_id}) as split_task:
                            run_visual_task_pipeline(
                                task_id=task_id,
                                user_id=user_id,
                                apply_to_link_record=False,
                                reuse_existing_outputs=True,
                            )

                plan_task.assert_not_called()
                generate_task.assert_not_called()
                split_task.assert_called_once()
            finally:
                database.DATABASE_PATH = original_path

    def test_normal_rerun_with_current_prompt_resets_outputs_and_replans(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                task_id = "visual-current-rerun"
                user_id = "user-1"
                mother_path = str(Path(tmpdir) / "current-mother.png")
                Path(mother_path).write_bytes(b"current image bytes")
                with database.get_connection() as conn:
                    ensure_visual_generation_schema(conn)
                    self.insert_visual_task(
                        conn=conn,
                        task_id=task_id,
                        user_id=user_id,
                        tmpdir=tmpdir,
                        status=TASK_STATUS_COMPLETED,
                        prompt_text="current mother prompt",
                        mother_image_path=mother_path,
                        analysis_json={"visualPromptLogicVersion": VISUAL_PROMPT_LOGIC_VERSION},
                    )
                    conn.execute(
                        """
                        INSERT INTO visual_generation_modules (
                            id, task_id, panel_index, position, slot_type, title, purpose,
                            prompt, output_path, output_url, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{task_id}-panel-1",
                            task_id,
                            1,
                            "",
                            "",
                            "",
                            "",
                            "current panel prompt",
                            str(Path(tmpdir) / "current-panel.webp"),
                            "https://example.test/current-panel.webp",
                            "split",
                            database.utc_now_text(),
                            database.utc_now_text(),
                        ),
                    )

                with patch("app.modules.visual_generation.service.plan_visual_task", return_value={"id": task_id, "promptText": "new prompt"}) as plan_task:
                    with patch("app.modules.visual_generation.service.generate_visual_task", return_value={"id": task_id}) as generate_task:
                        run_visual_task_pipeline(
                            task_id=task_id,
                            user_id=user_id,
                            apply_to_link_record=False,
                        )

                plan_task.assert_called_once()
                generate_task.assert_called_once()
                with database.get_connection() as conn:
                    row = conn.execute(
                        "SELECT prompt_text, mother_image_path, manifest_json FROM visual_generation_tasks WHERE id = ?",
                        (task_id,),
                    ).fetchone()
                    module_count = conn.execute(
                        "SELECT COUNT(*) FROM visual_generation_modules WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()[0]
                self.assertEqual(row["prompt_text"], "")
                self.assertIsNone(row["mother_image_path"])
                self.assertEqual(row["manifest_json"], "{}")
                self.assertEqual(module_count, 0)
            finally:
                database.DATABASE_PATH = original_path

    def test_stale_visual_prompt_resets_outputs_and_replans(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                task_id = "visual-stale-prompt"
                user_id = "user-1"
                mother_path = str(Path(tmpdir) / "old-mother.png")
                Path(mother_path).write_bytes(b"old image bytes")
                with database.get_connection() as conn:
                    ensure_visual_generation_schema(conn)
                    self.insert_visual_task(
                        conn=conn,
                        task_id=task_id,
                        user_id=user_id,
                        tmpdir=tmpdir,
                        status=TASK_STATUS_COMPLETED,
                        prompt_text="old mother prompt",
                        mother_image_path=mother_path,
                    )
                    conn.execute(
                        """
                        INSERT INTO visual_generation_modules (
                            id, task_id, panel_index, position, slot_type, title, purpose,
                            prompt, output_path, output_url, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{task_id}-panel-1",
                            task_id,
                            1,
                            "",
                            "",
                            "",
                            "",
                            "old panel prompt",
                            str(Path(tmpdir) / "old-panel.webp"),
                            "https://example.test/old-panel.webp",
                            "split",
                            database.utc_now_text(),
                            database.utc_now_text(),
                        ),
                    )

                with patch("app.modules.visual_generation.service.plan_visual_task", return_value={"id": task_id, "promptText": "new prompt"}) as plan_task:
                    with patch("app.modules.visual_generation.service.generate_visual_task", return_value={"id": task_id}) as generate_task:
                        run_visual_task_pipeline(
                            task_id=task_id,
                            user_id=user_id,
                            apply_to_link_record=False,
                        )

                plan_task.assert_called_once()
                generate_task.assert_called_once()
                with database.get_connection() as conn:
                    row = conn.execute(
                        "SELECT prompt_text, mother_image_path, manifest_json FROM visual_generation_tasks WHERE id = ?",
                        (task_id,),
                    ).fetchone()
                    module_count = conn.execute(
                        "SELECT COUNT(*) FROM visual_generation_modules WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()[0]
                self.assertEqual(row["prompt_text"], "")
                self.assertIsNone(row["mother_image_path"])
                self.assertEqual(row["manifest_json"], "{}")
                self.assertEqual(module_count, 0)
            finally:
                database.DATABASE_PATH = original_path

    def test_visual_prompt_stale_detection_uses_logic_version(self):
        self.assertTrue(
            visual_task_prompt_is_stale(
                {
                    "promptText": "old prompt",
                    "analysis": {},
                    "manifest": {},
                    "modules": [],
                }
            )
        )
        self.assertFalse(
            visual_task_prompt_is_stale(
                {
                    "promptText": "current prompt",
                    "analysis": {"visualPromptLogicVersion": VISUAL_PROMPT_LOGIC_VERSION},
                    "manifest": {},
                    "modules": [],
                }
            )
        )

    def test_late_failure_does_not_override_completed_split_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                task_id = "visual-complete"
                user_id = "user-1"
                with database.get_connection() as conn:
                    ensure_visual_generation_schema(conn)
                    conn.execute(
                        """
                        INSERT INTO visual_generation_tasks (
                            id, user_id, link_record_id, product_id, mode, layout, requested_count,
                            status, source_image_ref, record_json, mother_image_path, manifest_json,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task_id,
                            user_id,
                            "record-1",
                            "product-1",
                            "main-gallery",
                            "3x3",
                            2,
                            TASK_STATUS_COMPLETED,
                            "https://example.test/source.jpg",
                            "{}",
                            str(Path(tmpdir) / "mother.png"),
                            json.dumps({"panels": [{"panelIndex": 1}, {"panelIndex": 2}]}),
                            database.utc_now_text(),
                            database.utc_now_text(),
                        ),
                    )
                    for index in (1, 2):
                        conn.execute(
                            """
                            INSERT INTO visual_generation_modules (
                                id, task_id, panel_index, position, slot_type, title, purpose,
                                prompt, output_path, output_url, status, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                f"{task_id}-panel-{index}",
                                task_id,
                                index,
                                "",
                                "",
                                "",
                                "",
                                "",
                                str(Path(tmpdir) / f"panel-{index}.webp"),
                                f"https://example.test/panel-{index}.webp",
                                "split",
                                database.utc_now_text(),
                                database.utc_now_text(),
                            ),
                        )

                mark_task_failed(task_id, user_id, "AI request timed out: The read operation timed out")

                with database.get_connection() as conn:
                    row = conn.execute(
                        "SELECT status, error_message FROM visual_generation_tasks WHERE id = ?",
                        (task_id,),
                    ).fetchone()
                self.assertEqual(row["status"], TASK_STATUS_COMPLETED)
                self.assertIsNone(row["error_message"])
            finally:
                database.DATABASE_PATH = original_path

    def test_retry_waiting_clears_previous_error_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                task_id = "visual-retry"
                user_id = "user-1"
                with database.get_connection() as conn:
                    ensure_visual_generation_schema(conn)
                    self.insert_visual_task(
                        conn=conn,
                        task_id=task_id,
                        user_id=user_id,
                        tmpdir=tmpdir,
                    )
                    conn.execute(
                        "UPDATE visual_generation_tasks SET error_message = ? WHERE id = ?",
                        ("old failed request", task_id),
                    )

                mark_task_retry_waiting(task_id, user_id, "current transient failure")

                with database.get_connection() as conn:
                    row = conn.execute(
                        "SELECT status, error_message FROM visual_generation_tasks WHERE id = ?",
                        (task_id,),
                    ).fetchone()
                self.assertEqual(row["status"], TASK_STATUS_RETRY_WAITING)
                self.assertIsNone(row["error_message"])
            finally:
                database.DATABASE_PATH = original_path

    def test_quantity_only_single_skus_bind_reference_images_to_source_titles(self):
        record = {
            "id": "record-quantity",
            "productId": "product-quantity",
            "productTitle": "Mixed dice bundle",
            "sourceLinks": [
                {"id": "source-metal", "title": "2pcs stainless steel decision dice"},
                {"id": "source-wood", "title": "1 Pack wooden food choice dice"},
            ],
            "skuEntries": [
                {
                    "id": "sku-metal",
                    "order": 1,
                    "kind": "single",
                    "name": "2pcs",
                    "imageUrl": "https://example.test/metal-dice.jpg",
                    "sourceSkuLinks": [
                        {
                            "sourceId": "source-metal",
                            "sourceTitle": "Fallback metal title",
                            "sourceSkuKey": "source-metal:2pcs",
                            "specText": "Quantity: 2pcs",
                            "optionText": "2pcs",
                            "imageUrl": "https://example.test/metal-dice.jpg",
                        }
                    ],
                    "componentSkus": [],
                },
                {
                    "id": "sku-wood",
                    "order": 2,
                    "kind": "single",
                    "name": "1 Pack",
                    "imageUrl": "https://example.test/wood-dice.jpg",
                    "sourceSkuLinks": [
                        {
                            "sourceId": "source-wood",
                            "sourceTitle": "Fallback wood title",
                            "sourceSkuKey": "source-wood:1-pack",
                            "specText": "Quantity: 1 Pack",
                            "optionText": "1 Pack",
                            "imageUrl": "https://example.test/wood-dice.jpg",
                        }
                    ],
                    "componentSkus": [],
                },
            ],
        }
        context = build_visual_prompt_context(
            task={"mode": "main-gallery", "requestedCount": 9},
            record=record,
            reference_refs=[
                {
                    "url": "https://example.test/metal-dice.jpg",
                    "label": "Selected SKU: 2pcs / Product title: 2pcs stainless steel decision dice",
                    "role": "sales-sku",
                },
                {
                    "url": "https://example.test/wood-dice.jpg",
                    "label": "Selected SKU: 1 Pack / Product title: 1 Pack wooden food choice dice",
                    "role": "sales-sku",
                },
            ],
        )

        self.assertEqual(
            [
                (item["referenceImageIndex"], item["skuName"], item["sourceProductTitle"])
                for item in context["skuReferenceBindings"]
            ],
            [
                (1, "2pcs", "2pcs stainless steel decision dice"),
                (2, "1 Pack", "1 Pack wooden food choice dice"),
            ],
        )
        self.assertIn("visual source of truth", context["skuReferenceBindings"][0]["visualLock"])
        self.assertIn("facet/side count", context["skuReferenceBindings"][0]["visualLock"])
        self.assertIn("visual source reference image 1", context["skuReferenceBindings"][0]["bindingText"])

    def test_combo_sku_context_preserves_component_source_binding(self):
        record = {
            "id": "record-1",
            "productId": "product-1",
            "productTitle": "Mini tote bag bundle",
            "sourceLinks": [
                {"id": "source-a", "title": "Pale mini tote bag"},
                {"id": "source-b", "title": "Striped mini tote bag set"},
            ],
            "skuEntries": [
                {
                    "id": "sku-1",
                    "order": 1,
                    "kind": "combo",
                    "name": "1pc + 6pc",
                    "componentSkus": [
                        {
                            "name": "1pc",
                            "specText": "1pc",
                            "sourceId": "source-a",
                            "sourceTitle": "Shop A",
                            "imageUrl": "https://example.test/pale-1pc.jpg",
                        },
                        {
                            "name": "6pc",
                            "specText": "6pc",
                            "sourceId": "source-b",
                            "sourceTitle": "Shop B",
                            "imageUrl": "https://example.test/striped-6pc.jpg",
                        },
                    ],
                }
            ],
        }
        context = build_visual_prompt_context(
            task={"mode": "sku-gallery", "requestedCount": 1},
            record=record,
            reference_refs=[
                {"url": "https://example.test/pale-1pc.jpg", "label": "Pale mini tote bag / 1pc", "role": "sales-sku"},
                {
                    "url": "https://example.test/striped-6pc.jpg",
                    "label": "Striped mini tote bag set / 6pc",
                    "role": "sales-sku",
                },
            ],
        )

        self.assertEqual(context["skuNames"], ["1pc + 6pc"])
        self.assertIn("skuBindings", context)
        self.assertEqual(context["skuBindings"][0]["skuName"], "1pc + 6pc")
        self.assertEqual(context["skuBindings"][0]["compositionText"], "1pc from Pale mini tote bag + 6pc from Striped mini tote bag set")
        self.assertEqual(
            context["skuBindings"][0]["components"],
            [
                {
                    "componentIndex": 1,
                    "componentName": "1pc",
                    "sourceTitle": "Pale mini tote bag",
                    "specText": "1pc",
                    "optionText": "",
                    "referenceImageIndex": 1,
                },
                {
                    "componentIndex": 2,
                    "componentName": "6pc",
                    "sourceTitle": "Striped mini tote bag set",
                    "specText": "6pc",
                    "optionText": "",
                    "referenceImageIndex": 2,
                },
            ],
        )
        self.assertEqual(context["skuCombinationBindings"][0]["compositionText"], "1pc from Pale mini tote bag + 6pc from Striped mini tote bag set")
        self.assertEqual(
            [
                (
                    item["referenceImageIndex"],
                    item["skuName"],
                    item["skuKind"],
                    item["componentName"],
                    item["sourceProductTitle"],
                    item["specText"],
                    item["optionText"],
                )
                for item in context["skuReferenceBindings"]
            ],
            [
                (1, "1pc + 6pc", "combo", "1pc", "Pale mini tote bag", "1pc", ""),
                (2, "1pc + 6pc", "combo", "6pc", "Striped mini tote bag set", "6pc", ""),
            ],
        )
        self.assertIn("visual source of truth", context["skuReferenceBindings"][0]["visualLock"])

        mother_prompt = build_mother_prompt_from_plan(
            {
                "productUnderstanding": {"productTitle": "Mini tote bag bundle"},
                "skuBindings": context["skuBindings"],
                "skuCombinationBindings": context["skuCombinationBindings"],
                "skuReferenceBindings": context["skuReferenceBindings"],
                "visualTaskPlan": {
                    "requestedCount": 1,
                    "layout": "1x1",
                    "modules": [
                        {
                            "position": 1,
                            "slotType": "package-combo",
                            "title": "Combo Content",
                            "purpose": "show exact combo contents",
                            "targetSkuName": "1pc + 6pc",
                            "targetSkuBinding": "1pc from Pale mini tote bag + 6pc from Striped mini tote bag set",
                        }
                    ],
                },
                "panelPromptPlan": {
                    "panels": [
                        {
                            "position": 1,
                            "slotType": "package-combo",
                            "targetSkuName": "1pc + 6pc",
                            "targetSkuBinding": "1pc from Pale mini tote bag + 6pc from Striped mini tote bag set",
                            "panelPrompt": "Create a square ecommerce combo image.",
                        }
                    ]
                },
            },
            "1x1",
        )
        self.assertIn("1pc from Pale mini tote bag + 6pc from Striped mini tote bag set", mother_prompt)
        self.assertIn("Reference image to SKU/source product title bindings", mother_prompt)
        self.assertIn("product title Pale mini tote bag", mother_prompt)
        self.assertIn("product title Striped mini tote bag set", mother_prompt)

    def test_dice_prompt_preserves_reference_geometry_and_image_first_binding(self):
        analysis_instruction = build_product_analysis_instruction(
            {
                "productTitle": "Mixed dice options",
                "skuReferenceBindings": [
                    {"referenceImageIndex": 1, "skuName": "2pcs", "sourceProductTitle": "2pcs decision dice"},
                    {"referenceImageIndex": 2, "skuName": "1 Pack", "sourceProductTitle": "wood twelve-sided die"},
                ],
            }
        )
        self.assertIn("attached image itself is the visual source of truth", analysis_instruction)
        self.assertIn("six-sided rounded cube-style die", analysis_instruction)
        self.assertIn("twelve-sided dodecahedron-style die", analysis_instruction)

        mother_prompt = build_mother_prompt_from_plan(
            {
                "productUnderstanding": {
                    "productTitle": "Mixed dice options",
                    "referenceAnalyses": [
                        {
                            "index": 1,
                            "visualIdentity": "2pcs white printed dice",
                            "geometry": "six-sided rounded cube-style die",
                            "facetOrSideCount": "6 sides",
                            "mustPreserve": ["two six-sided rounded cube-style dice"],
                            "doNotChange": ["do not convert into twelve-sided dice"],
                        },
                        {
                            "index": 2,
                            "visualIdentity": "1 Pack wooden die",
                            "geometry": "twelve-sided dodecahedron-style die",
                            "facetOrSideCount": "12 sides",
                            "mustPreserve": ["one twelve-sided wooden dodecahedron-style die"],
                            "doNotChange": ["do not convert into cube-style dice"],
                        },
                    ],
                },
                "skuReferenceBindings": [
                    {
                        "referenceImageIndex": 1,
                        "skuName": "2pcs",
                        "sourceProductTitle": "2pcs decision dice",
                        "visualLock": "Reference image 1 is the visual source of truth for SKU 2pcs. Preserve six-sided rounded cube-style geometry.",
                    },
                    {
                        "referenceImageIndex": 2,
                        "skuName": "1 Pack",
                        "sourceProductTitle": "wood twelve-sided die",
                        "visualLock": "Reference image 2 is the visual source of truth for SKU 1 Pack. Preserve twelve-sided dodecahedron-style geometry.",
                    },
                ],
                "visualTaskPlan": {
                    "requestedCount": 1,
                    "layout": "1x1",
                    "modules": [
                        {
                            "position": 1,
                            "slotType": "comparison",
                            "title": "Compare Options",
                            "purpose": "compare exact dice options",
                            "targetSkuName": "2pcs",
                            "targetSkuBinding": "reference 1 is 2pcs and reference 2 is 1 Pack",
                            "visualIdentityLock": "2pcs must remain two six-sided rounded cube-style dice; 1 Pack must remain one twelve-sided wooden die.",
                        }
                    ],
                },
                "panelPromptPlan": {
                    "panels": [
                        {
                            "position": 1,
                            "slotType": "comparison",
                            "targetSkuName": "2pcs",
                            "targetSkuBinding": "reference 1 is 2pcs and reference 2 is 1 Pack",
                            "panelPrompt": "Compare the two bound dice SKUs.",
                        }
                    ]
                },
            },
            "1x1",
        )
        self.assertIn("Geometry lock", mother_prompt)
        self.assertIn("six-sided rounded cube-style die must not become", mother_prompt)
        self.assertIn("twelve-sided/dodecahedron wooden die", mother_prompt)
        self.assertIn("2pcs must remain two six-sided rounded cube-style dice", mother_prompt)


if __name__ == "__main__":
    unittest.main()
