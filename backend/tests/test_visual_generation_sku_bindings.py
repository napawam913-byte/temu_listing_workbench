import unittest

from app.modules.visual_generation.service import build_visual_prompt_context
from app.modules.visual_generation.planner import build_mother_prompt_from_plan


class VisualGenerationSkuBindingTest(unittest.TestCase):
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

        mother_prompt = build_mother_prompt_from_plan(
            {
                "productUnderstanding": {"productTitle": "Mini tote bag bundle"},
                "skuBindings": context["skuBindings"],
                "skuCombinationBindings": context["skuCombinationBindings"],
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


if __name__ == "__main__":
    unittest.main()
