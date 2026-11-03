"""Unit tests for Flaschenpost API helpers, category filters, interactive preview, and lazy resolution."""

from __future__ import annotations

import asyncio
import importlib.util
import math
import sys
import types
import unittest
from pathlib import Path
from typing import Any

# Allow running unit tests directly in lightweight Python environments without
# importing `custom_components/flaschenpost/__init__.py` (which requires full HA).
_ROOT = Path(__file__).resolve().parents[1]
_PKG_DIR = _ROOT / "custom_components" / "flaschenpost"
if "custom_components.flaschenpost" not in sys.modules:
    cc_pkg = types.ModuleType("custom_components")
    cc_pkg.__path__ = [str(_ROOT / "custom_components")]
    fp_pkg = types.ModuleType("custom_components.flaschenpost")
    fp_pkg.__path__ = [str(_PKG_DIR)]
    sys.modules.setdefault("custom_components", cc_pkg)
    sys.modules["custom_components.flaschenpost"] = fp_pkg
    for mod_name in ("const", "api", "shopping_list"):
        spec = importlib.util.spec_from_file_location(
            f"custom_components.flaschenpost.{mod_name}",
            _PKG_DIR / f"{mod_name}.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)

from custom_components.flaschenpost.api import (
    FlaschenpostApiClient,
    cents_to_eur,
    compute_basket_class,
    extract_product_categories,
    extract_product_summary,
    matches_category_filter,
    matches_query_qualifiers,
    normalize_search_queries,
    parse_price_per_unit_text,
)
from custom_components.flaschenpost.const import (
    CONF_DELIVERY_LOCATION,
    CONF_WAREHOUSE_ID,
    PAYMENT_CREDIT_CARD,
    PAYMENT_SEPA,
    SERVICE_BUY_CART,
    SORT_PRICE_PER_KG,
    SORT_PRICE_PER_UNIT,
    UNIT_TYPE_CRATE,
    UNIT_TYPE_UNIT,
    UNIT_TYPE_WEIGHT_G,
)
from custom_components.flaschenpost.shopping_list import (
    FlaschenpostShoppingListManager,
    build_pinned_spec_summary,
    build_preview_spec,
    estimate_candidate_pack_plan,
    format_shopping_item_summary,
    format_shopping_spec_summary,
    parse_shopping_item_details,
    parse_shopping_item_spec,
    parse_shopping_item_summary,
)


class _FakeApiClient:
    """Stub client verifying lazy cart-time resolution, category filters, weight math, and crate filtering."""

    def __init__(self) -> None:
        self.cart_positions_calls: list[list[dict[str, int]]] = []
        self.resolve_calls: list[tuple[str, str | None, str, float]] = []
        self.cleared_cart: bool = False

    async def async_get_categories(
        self, warehouse_id: int | None = None
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": "cat-kochen",
                "external_id": "37",
                "name": "Kochen & Vorrat",
                "slug": "kochen-vorrat",
                "subcategories": [
                    {
                        "id": "sub-reis",
                        "external_id": "595",
                        "name": "Reis & Getreide",
                        "slug": "reis-getreide",
                    }
                ],
            },
            {
                "id": "cat-molkerei",
                "external_id": "30",
                "name": "Eier & Molkerei",
                "slug": "eier-molkerei",
                "subcategories": [
                    {
                        "id": "sub-pudding",
                        "external_id": "530",
                        "name": "Pudding, Grieß & Milchreis",
                        "slug": "pudding-griess-milchreis",
                    }
                ],
            },
        ]

    async def async_search_products(
        self,
        query: str,
        *,
        limit: int = 10,
        warehouse_id: int | None = None,
        category: str | None = None,
        name_contains: str | None = None,
        sort_by: str | None = None,
        only_available: bool = True,
        only_crates: bool = False,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        ql = query.lower()
        if "milchreis" in ql:
            dry = {
                "article_id": 10495,
                "name": "Oryza Milch Reis",
                "description": "400g",
                "package_weight_g": 400.0,
                "price_eur": 2.39,
                "price_per_kg_eur": 5.98,
                "is_available": True,
                "categories": ["Kochen & Vorrat", "Reis & Getreide", "Loser Reis"],
                "category_slugs": ["kochen-vorrat", "reis-getreide", "loser-reis"],
            }
            dairy = {
                "article_id": 7963,
                "name": "Müller Milchreis Zimt",
                "description": "200g",
                "package_weight_g": 200.0,
                "price_eur": 0.69,
                "price_per_kg_eur": 3.45,
                "is_available": True,
                "categories": ["Eier & Molkerei", "Pudding, Grieß & Milchreis"],
                "category_slugs": ["eier-molkerei", "pudding-griess-milchreis"],
            }
            res = [dry, dairy]
            if category:
                res = [c for c in res if matches_category_filter(c, category)]
            return res[:limit]
        return []

    async def async_resolve_item_for_cart(
        self,
        query: str,
        *,
        unit_type: str = UNIT_TYPE_UNIT,
        target_amount_base: float = 1.0,
        article_id: int | None = None,
        category: str | None = None,
        sort_by: str | None = None,
        name_contains: str | None = None,
    ) -> dict[str, Any] | None:
        self.resolve_calls.append((query, category, unit_type, target_amount_base))
        ql = query.lower()
        if "milchreis" in ql:
            if category and "reis & getreide" in category.lower():
                # Dry pudding rice from "Kochen & Vorrat -> Reis & Getreide"
                pkg_g = 400.0
                qty = max(1, math.ceil(target_amount_base / pkg_g - 1e-9))
                return {
                    "article_id": 10495,
                    "quantity": qty,
                    "unit_type": unit_type,
                    "requested_amount_base": target_amount_base,
                    "delivered_amount_base": qty * pkg_g,
                    "line_total_eur": round(qty * 2.39, 2),
                    "product": {
                        "article_id": 10495,
                        "name": "Oryza Milch Reis",
                        "description": "400g",
                        "package_weight_g": 400.0,
                        "categories": ["Kochen & Vorrat", "Reis & Getreide", "Loser Reis"],
                        "price_eur": 2.39,
                        "price_per_kg_eur": 5.98,
                    },
                }
            # Without category filter, dairy cup in "Eier & Molkerei -> Pudding, Grieß & Milchreis" has lower €/kg
            pkg_g = 200.0
            qty = max(1, math.ceil(target_amount_base / pkg_g - 1e-9))
            return {
                "article_id": 7963,
                "quantity": qty,
                "unit_type": unit_type,
                "requested_amount_base": target_amount_base,
                "delivered_amount_base": qty * pkg_g,
                "line_total_eur": round(qty * 0.69, 2),
                "product": {
                    "article_id": 7963,
                    "name": "Müller Milchreis Zimt",
                    "description": "200g",
                    "package_weight_g": 200.0,
                    "categories": ["Eier & Molkerei", "Pudding, Grieß & Milchreis", "Milchreis"],
                    "price_eur": 0.69,
                    "price_per_kg_eur": 3.45,
                },
            }
        if "joghurt" in ql:
            # 600g (4 x 150g) at 1.48 €/kg beats 500g at 1.58 €/kg -> 2 packs = 1200g (1.2kg)
            pkg_g = 600.0
            qty = (
                max(1, math.ceil(target_amount_base / pkg_g - 1e-9))
                if unit_type == UNIT_TYPE_WEIGHT_G
                else max(1, round(target_amount_base))
            )
            return {
                "article_id": 28242,
                "quantity": qty,
                "unit_type": unit_type,
                "requested_amount_base": target_amount_base,
                "delivered_amount_base": qty * pkg_g,
                "line_total_eur": round(qty * 0.89, 2),
                "product": {
                    "article_id": 28242,
                    "name": "K-Classic Naturjoghurt 1,5%",
                    "description": "4 x 150g",
                    "package_weight_g": 600.0,
                    "price_eur": 0.89,
                    "price_per_kg_eur": 1.48,
                },
            }
        if "puten schnitzel" in ql:
            pkg_g = 500.0
            qty = max(1, math.ceil(target_amount_base / pkg_g - 1e-9))
            return {
                "article_id": 29997,
                "quantity": qty,
                "unit_type": unit_type,
                "requested_amount_base": target_amount_base,
                "delivered_amount_base": qty * pkg_g,
                "line_total_eur": round(qty * 5.99, 2),
                "product": {
                    "article_id": 29997,
                    "name": "K-Purland Puten Schnitzel",
                    "description": "500g",
                    "package_weight_g": 500.0,
                    "price_eur": 5.99,
                    "price_per_kg_eur": 11.98,
                },
            }
        if "pepsi zero" in ql and unit_type == UNIT_TYPE_CRATE:
            qty = max(1, math.ceil(target_amount_base - 1e-9))
            return {
                "article_id": 1838,
                "quantity": qty,
                "unit_type": unit_type,
                "requested_amount_base": target_amount_base,
                "delivered_amount_base": float(qty),
                "line_total_eur": round(qty * 12.99, 2),
                "product": {
                    "article_id": 1838,
                    "name": "Pepsi Zero Zucker",
                    "description": "12 x 1L (PET)",
                    "price_eur": 12.99,
                    "price_per_liter_eur": 1.08,
                },
            }
        if "karotten" in ql:
            pkg_g = 1000.0
            qty = max(1, math.ceil(target_amount_base / pkg_g - 1e-9))
            return {
                "article_id": 30399,
                "quantity": qty,
                "unit_type": unit_type,
                "requested_amount_base": target_amount_base,
                "delivered_amount_base": qty * pkg_g,
                "line_total_eur": round(qty * 1.49, 2),
                "product": {
                    "article_id": 30399,
                    "name": "Möhren",
                    "description": "1kg",
                    "package_weight_g": 1000.0,
                    "price_eur": 1.49,
                    "price_per_kg_eur": 1.49,
                },
            }
        return None

    async def async_get_cart(self) -> dict[str, Any]:
        return {"id": "cart-123", "lineItems": []}

    async def async_create_new_cart(self) -> dict[str, Any]:
        self.cleared_cart = True
        return {"id": "cart-123", "lineItems": []}

    async def async_set_cart_positions(
        self, positions: list[dict[str, int]]
    ) -> dict[str, Any]:
        self.cart_positions_calls.append(positions)
        return {"id": "cart-123", "lineItems": []}


class TestFlaschenpostHelpers(unittest.TestCase):
    """Test helper functions, category filters, interactive preview, and lazy resolution."""

    def test_money_and_basket_class(self) -> None:
        self.assertEqual(
            cents_to_eur({"centAmount": 1249, "fractionDigits": 2}), 12.49
        )
        self.assertEqual(cents_to_eur(None), 0.0)
        self.assertEqual(compute_basket_class(2500), "BELOWMOV")
        self.assertEqual(compute_basket_class(6000), "ABOVEMOV")
        self.assertEqual(compute_basket_class(9500), "ABOVETHRESHOLD")

    def test_parse_price_per_unit_text(self) -> None:
        self.assertEqual(parse_price_per_unit_text("(1,48 €/kg)"), (1.48, "kg"))
        self.assertEqual(
            parse_price_per_unit_text("12 x 1L (0,71 €/l)"), (0.71, "l")
        )
        self.assertEqual(parse_price_per_unit_text("(0,25 €/100g)"), (2.5, "kg"))
        self.assertEqual(parse_price_per_unit_text(None), (None, None))

    def test_extract_product_summary_weight_and_crate_detection(self) -> None:
        yogurt = {
            "id": "prod-yogurt",
            "name": {"de-DE": "K-Classic  Naturjoghurt 1,5%"},
            "masterVariant": {
                "sku": "28242",
                "attributes": [
                    {"name": "ArticleDescription", "value": "4 x 150g"},
                    {"name": "ItemsInFrame", "value": 1},
                    {"name": "Volume", "value": 600},
                    {"name": "VolumeUnit", "value": {"key": "g"}},
                    {"name": "ContainerType", "value": {"key": "None_Individual"}},
                    {"name": "IsAvailable", "value": True},
                ],
                "price": {
                    "value": {"centAmount": 89, "fractionDigits": 2},
                    "custom": {"fields": {"PricePerUnitText": "(1,48 €/kg)"}},
                },
            },
        }
        s_yog = extract_product_summary(yogurt)
        self.assertEqual(s_yog["package_weight_g"], 600.0)
        self.assertEqual(s_yog["price_per_kg_eur"], 1.48)
        self.assertFalse(s_yog["is_crate"])

        pepsi_crate = {
            "id": "prod-pepsi",
            "name": {"de-DE": "Pepsi Zero Zucker"},
            "masterVariant": {
                "sku": "1838",
                "attributes": [
                    {"name": "ArticleDescription", "value": "12 x 1L (PET)"},
                    {"name": "ItemsInFrame", "value": 12},
                    {"name": "Volume", "value": 1000},
                    {"name": "VolumeUnit", "value": {"key": "ml"}},
                    {"name": "ContainerType", "value": {"key": "MWPET_Individual"}},
                    {"name": "IsAvailable", "value": True},
                ],
                "price": {
                    "value": {"centAmount": 1299, "fractionDigits": 2},
                    "custom": {"fields": {"PricePerUnitText": "(1,08 €/L)"}},
                },
            },
        }
        s_crate = extract_product_summary(pepsi_crate)
        self.assertTrue(s_crate["is_crate"])
        self.assertEqual(s_crate["package_volume_ml"], 12000.0)

        sixpack_small = {
            "id": "prod-sixpack",
            "name": {"de-DE": "Coca-Cola Zero Sugar"},
            "masterVariant": {
                "sku": "23702",
                "attributes": [
                    {"name": "ArticleDescription", "value": "6 x 0,33L (Glas)"},
                    {"name": "ItemsInFrame", "value": 6},
                    {"name": "Volume", "value": 330},
                    {"name": "VolumeUnit", "value": {"key": "ml"}},
                    {"name": "ContainerType", "value": {"key": "MWGlass_Individual"}},
                ],
                "price": {"value": {"centAmount": 699, "fractionDigits": 2}},
            },
        }
        self.assertFalse(extract_product_summary(sixpack_small)["is_crate"])

    def test_category_extraction_and_filtering(self) -> None:
        dry_rice_product = {
            "id": "prod-oryza",
            "name": {"de-DE": "Oryza Milch Reis"},
            "categories": [
                {
                    "obj": {
                        "name": {"de-DE": "Loser Reis"},
                        "slug": {"de-DE": "loser-reis"},
                        "custom": {"type": {"key": "fp-category-productgroup"}},
                        "ancestors": [
                            {
                                "obj": {
                                    "name": {"de-DE": "Kochen & Vorrat"},
                                    "slug": {"de-DE": "kochen-vorrat"},
                                    "custom": {"type": {"key": "fp-category"}},
                                    "ancestors": [],
                                }
                            },
                            {
                                "obj": {
                                    "name": {"de-DE": "Reis & Getreide"},
                                    "slug": {"de-DE": "reis-getreide"},
                                    "custom": {"type": {"key": "fp-category-subcategory"}},
                                    "ancestors": [],
                                }
                            },
                        ],
                    }
                },
                {
                    "obj": {
                        "name": {"de-DE": "Oryza"},
                        "slug": {"de-DE": "oryza"},
                        "custom": {"type": {"key": "fp-category-brand"}},
                        "ancestors": [],
                    }
                },
            ],
            "masterVariant": {
                "sku": "10495",
                "attributes": [
                    {"name": "ArticleDescription", "value": "400g"},
                    {"name": "Volume", "value": 400},
                    {"name": "VolumeUnit", "value": {"key": "g"}},
                ],
                "price": {"value": {"centAmount": 239, "fractionDigits": 2}},
            },
        }
        cat_names, cat_slugs, brand = extract_product_categories(dry_rice_product)
        self.assertEqual(
            cat_names, ["Kochen & Vorrat", "Reis & Getreide", "Loser Reis"]
        )
        self.assertIn("reis-getreide", cat_slugs)
        self.assertEqual(brand, "Oryza")

        dry_summary = extract_product_summary(dry_rice_product)
        dairy_summary = {
            "article_id": 7963,
            "name": "Müller Milchreis Zimt",
            "description": "200g",
            "categories": [
                "Eier & Molkerei",
                "Pudding, Grieß & Milchreis",
                "Milchreis",
            ],
            "category_slugs": [
                "eier-molkerei",
                "pudding-griess-milchreis",
                "milchreis",
            ],
        }

        # Both match query "Milchreis" (including space-separated "Oryza Milch Reis")
        self.assertTrue(matches_query_qualifiers(dry_summary, "Milchreis"))
        self.assertTrue(matches_query_qualifiers(dairy_summary, "Milchreis"))

        # Category filter "Reis & Getreide" accepts dry rice and rejects dairy cups
        self.assertTrue(matches_category_filter(dry_summary, "Reis & Getreide"))
        self.assertTrue(
            matches_category_filter(dry_summary, "Kochen & Vorrat::Reis & Getreide")
        )
        self.assertTrue(matches_category_filter(dry_summary, "reis-getreide"))
        self.assertFalse(matches_category_filter(dairy_summary, "Reis & Getreide"))
        self.assertTrue(
            matches_category_filter(dairy_summary, "Pudding, Grieß & Milchreis")
        )

    def test_search_synonyms_and_qualifiers(self) -> None:
        self.assertIn(
            "Schwip Schwap Zero",
            normalize_search_queries("Schwipp Schwapp Zero"),
        )
        self.assertIn("Möhren", normalize_search_queries("Karotten"))

        schwip = {
            "name": "Schwip Schwap ohne Zucker",
            "description": "12 x 1L (PET)",
        }
        self.assertTrue(matches_query_qualifiers(schwip, "Schwipp Schwapp Zero"))

        moehren = {"name": "Möhren", "description": "1kg"}
        self.assertTrue(matches_query_qualifiers(moehren, "Karotten"))

        # Blueberry yogurt should NOT match "Heidelbeeren"
        blueberry_yogurt = {
            "name": "Müller Joghurt mit der Ecke Schlemmer Heidelbeere",
            "description": "150g",
            "ingredients": "Joghurt, Heidelbeeren",
        }
        self.assertFalse(matches_query_qualifiers(blueberry_yogurt, "Heidelbeeren"))

    def test_parse_shopping_units_and_category_syntax(self) -> None:
        s_cat = parse_shopping_item_spec("500g Reis & Getreide::Milchreis")
        self.assertEqual(s_cat.unit_type, UNIT_TYPE_WEIGHT_G)
        self.assertEqual(s_cat.target_amount_base, 500.0)
        self.assertEqual(s_cat.category, "Reis & Getreide")
        self.assertEqual(s_cat.query, "Milchreis")
        self.assertEqual(
            format_shopping_spec_summary(s_cat),
            "500g Reis & Getreide::Milchreis",
        )

        # Prefix category syntax also works: "Reis & Getreide::500g Milchreis"
        s_cat_prefix = parse_shopping_item_spec("Reis & Getreide::500g Milchreis")
        self.assertEqual(s_cat_prefix.unit_type, UNIT_TYPE_WEIGHT_G)
        self.assertEqual(s_cat_prefix.target_amount_base, 500.0)
        self.assertEqual(s_cat_prefix.category, "Reis & Getreide")
        self.assertEqual(s_cat_prefix.query, "Milchreis")

        # Multi-level category path: "500g Kochen & Vorrat::Reis & Getreide::Milchreis"
        s_cat_hier = parse_shopping_item_spec(
            "500g Kochen & Vorrat::Reis & Getreide::Milchreis"
        )
        self.assertEqual(s_cat_hier.category, "Kochen & Vorrat::Reis & Getreide")
        self.assertEqual(s_cat_hier.query, "Milchreis")

        s1 = parse_shopping_item_spec("1kg Naturjoghurt")
        self.assertEqual(s1.unit_type, UNIT_TYPE_WEIGHT_G)
        self.assertEqual(s1.target_amount_base, 1000.0)
        self.assertEqual(s1.query, "Naturjoghurt")
        self.assertIsNone(s1.category)

        s2 = parse_shopping_item_spec("1,5kg Puten Schnitzel")
        self.assertEqual(s2.unit_type, UNIT_TYPE_WEIGHT_G)
        self.assertEqual(s2.target_amount_base, 1500.0)
        self.assertEqual(s2.query, "Puten Schnitzel")

        s3 = parse_shopping_item_spec("500g Heidelbeeren")
        self.assertEqual(s3.unit_type, UNIT_TYPE_WEIGHT_G)
        self.assertEqual(s3.target_amount_base, 500.0)
        self.assertEqual(s3.query, "Heidelbeeren")

        s4 = parse_shopping_item_spec("1 Kiste Pepsi Zero")
        self.assertEqual(s4.unit_type, UNIT_TYPE_CRATE)
        self.assertEqual(s4.target_amount_base, 1.0)
        self.assertEqual(s4.query, "Pepsi Zero")

        # Ensure "7Up" is not misparsed as quantity=7
        s5 = parse_shopping_item_spec("7Up")
        self.assertEqual(s5.unit_type, UNIT_TYPE_UNIT)
        self.assertEqual(s5.target_amount_base, 1.0)
        self.assertEqual(s5.query, "7Up")

        self.assertEqual(
            parse_shopping_item_summary("2x Gerolsteiner Medium #410"),
            (2, "Gerolsteiner Medium", 410),
        )
        self.assertEqual(
            parse_shopping_item_details("Joghurt 1,5% fett [€/kg]"),
            (1, "Joghurt 1,5% fett", None, SORT_PRICE_PER_KG),
        )
        self.assertEqual(
            parse_shopping_item_details("2x Joghurt 1,5% [€/unit]"),
            (2, "Joghurt 1,5%", None, SORT_PRICE_PER_UNIT),
        )
        self.assertEqual(
            format_shopping_item_summary(3, "Gerolsteiner Medium", 410),
            "3x Gerolsteiner Medium #410",
        )

    def test_interactive_preview_helpers(self) -> None:
        spec = build_preview_spec(
            "Milchreis",
            amount_prefix="500g",
            category_override="Reis & Getreide",
            sort_by="price_per_kg",
        )
        self.assertEqual(spec.unit_type, UNIT_TYPE_WEIGHT_G)
        self.assertEqual(spec.target_amount_base, 500.0)
        self.assertEqual(spec.category, "Reis & Getreide")
        self.assertEqual(spec.query, "Milchreis")
        self.assertEqual(spec.sort_by, SORT_PRICE_PER_KG)

        product = {
            "article_id": 10495,
            "name": "Oryza Milch Reis",
            "description": "400g",
            "package_weight_g": 400.0,
            "price_eur": 2.39,
            "price_per_kg_eur": 5.98,
        }
        plan = estimate_candidate_pack_plan(spec, product)
        self.assertEqual(plan["packs"], 2)
        self.assertEqual(plan["delivered_amount"], "800g")
        self.assertEqual(plan["line_total_eur"], 4.78)
        self.assertIn("5.98 EUR/kg", plan["base_metric"])
        self.assertEqual(
            build_pinned_spec_summary(spec, product),
            "500g Oryza Milch Reis #10495",
        )

    def test_preview_search_and_list_preview(self) -> None:
        async def _run() -> None:
            fake_client = _FakeApiClient()
            mgr = FlaschenpostShoppingListManager(client=fake_client)  # type: ignore[arg-type]

            # 1. Interactive preview search for "500g Reis & Getreide::Milchreis"
            preview = await mgr.async_preview_search(
                "Milchreis",
                amount_prefix="500g",
                category="Reis & Getreide",
            )
            self.assertEqual(preview["lazy_summary"], "500g Reis & Getreide::Milchreis")
            self.assertIsNotNone(preview["winner"])
            self.assertEqual(preview["winner"]["article_id"], 10495)
            self.assertEqual(preview["winner"]["quantity"], 2)
            self.assertTrue(any(c["article_id"] == 10495 for c in preview["candidates"]))
            self.assertIn("Oryza Milch Reis", preview["markdown"])

            # 2. Add to list and dry-run preview across lists
            await mgr.async_add_item(preview["lazy_summary"], list_name="Every week")
            await mgr.async_add_item("1kg Karotten", list_name="Every even week")

            list_prev = await mgr.async_preview_lists(list_names=["Every week", "Every even week"])
            self.assertEqual(len(list_prev["resolved_items"]), 2)
            self.assertGreater(list_prev["estimated_goods_eur"], 0.0)
            self.assertIn("Oryza Milch Reis", list_prev["markdown"])
            self.assertIn("Möhren", list_prev["markdown"])

            # Verify no cart positions were pushed during dry-run preview
            self.assertEqual(len(fake_client.cart_positions_calls), 0)

        asyncio.run(_run())

    def test_pick_available_slots(self) -> None:
        slots_resp = {
            "days": [
                {"date": "2026-11-04", "disabled": False},
                {"date": "2026-11-05", "disabled": True},
            ],
            "slots": [
                {
                    "type": "PREORDER",
                    "from": "2026-11-04T10:00:00Z",
                    "until": "2026-11-04T12:00:00Z",
                    "additionalData": {"display": "enable"},
                },
                {
                    "type": "PREORDER",
                    "from": "2026-11-04T12:00:00Z",
                    "until": "2026-11-04T14:00:00Z",
                    "additionalData": {"display": "disable"},
                },
            ],
        }
        valid = FlaschenpostApiClient.pick_available_slots(slots_resp)
        self.assertEqual(len(valid), 1)

    def test_delivery_polygon_and_warehouse_sync(self) -> None:
        async def _run() -> None:
            client = FlaschenpostApiClient(email="test@example.com", password="secret")

            requests_log = []
            async def _fake_request(method, url, authenticated=True, json_body=None, **kwargs):
                requests_log.append((method, url, authenticated, json_body))
                if "isInPolygonDeliveryArea" in url:
                    return "52.3554" in url
                if "refreshPolygonProperties" in url:
                    return {
                        "id": "cart-123",
                        "custom": {
                            "fields": {
                                "RecentlyUsedWarehouseId": 27,
                                "CustomerId": 12345,
                            }
                        },
                    }
                return {}

            client._request = _fake_request  # type: ignore[assignment]

            # In polygon check: True
            in_area = await client.async_is_in_polygon_delivery_area(52.3554, 9.3862)
            self.assertTrue(in_area)
            self.assertEqual(requests_log[0][0], "GET")
            self.assertIn("52.3554, 9.3862", requests_log[0][1])
            self.assertFalse(requests_log[0][2])  # authenticated=False

            # In polygon check: False
            out_area = await client.async_is_in_polygon_delivery_area(40.0, 10.0)
            self.assertFalse(out_area)

            # Refresh polygon properties updates client.warehouse_id
            cart = await client.async_refresh_polygon_properties()
            self.assertEqual(client.warehouse_id, 27)
            self.assertEqual(cart["id"], "cart-123")
            self.assertEqual(CONF_WAREHOUSE_ID, "warehouse_id")
            self.assertEqual(CONF_DELIVERY_LOCATION, "delivery_location")

        asyncio.run(_run())

    def test_saved_payment_methods_discovery(self) -> None:
        async def _run() -> None:
            client = FlaschenpostApiClient(email="test@example.com", password="secret")
            cart_data = {
                "id": "cart-123",
                "totalPrice": {"centAmount": 3000},
            }
            account_data = {
                "addresses": [
                    {
                        "key": "addr-1",
                        "custom": {"fields": {"AddressReference": "ref-abc"}},
                    }
                ],
                "custom": {
                    "fields": {
                        "PaymentInvoiceAllowed": True,
                        "PaypalCustomerIds": [
                            '{"shopperReference":"sref-1","customerId":"cid-1","customerEmailAddress":"paypal@example.com"}'
                        ],
                    }
                },
            }

            async def _fake_request(method, url, params=None, json_body=None, **kwargs):
                if url == "/webshop-cart-api/api/v4/cart":
                    return cart_data
                if "adyen/init" in url:
                    return {
                        "paymentId": "adyen-pay-1",
                        "adyenSessionResponse": {
                            "id": "session-1",
                            "sessionData": "sdata-1",
                        },
                    }
                if "direct/init" in url:
                    return {
                        "directDebitAccounts": [
                            {"ibanMasked": "DE89370400440532013000", "isBlackListed": False}
                        ]
                    }
                return {}

            client._request = _fake_request  # type: ignore[assignment]
            async def _fake_cart_data():
                return cart_data
            async def _fake_acc_data():
                return account_data
            client.async_get_cart = _fake_cart_data  # type: ignore[assignment]
            client.async_get_my_account = _fake_acc_data  # type: ignore[assignment]

            # Mock Adyen setup response
            class _FakeAdyenResponse:
                status = 200
                async def json(self):
                    return {
                        "storedPaymentMethods": [
                            {
                                "id": "stored-card-99",
                                "brand": "visa",
                                "lastFour": "4242",
                                "expiryMonth": "12",
                                "expiryYear": "2028",
                            }
                        ]
                    }
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass

            class _FakeSession:
                def post(self, url, json=None, **kwargs):
                    return _FakeAdyenResponse()

            client._session = _FakeSession()  # type: ignore[assignment]

            methods = await client.async_get_saved_payment_methods()
            method_ids = [m["id"] for m in methods]
            self.assertIn("credit_card:stored-card-99", method_ids)
            self.assertIn("paypal:cid-1", method_ids)
            self.assertIn("sepa:3000", method_ids)
            self.assertIn("invoice", method_ids)

            card_entry = next(m for m in methods if m["id"] == "credit_card:stored-card-99")
            self.assertEqual(card_entry["payment_method"], PAYMENT_CREDIT_CARD)
            self.assertEqual(card_entry["brand"], "visa")
            self.assertEqual(card_entry["last4"], "4242")
            self.assertIn("4242", card_entry["label"])

        asyncio.run(_run())

    def test_credit_card_place_order_flow(self) -> None:
        async def _run() -> None:
            client = FlaschenpostApiClient(email="test@example.com", password="secret")
            client._cart_id = "cart-uuid"
            recalc_cart = {
                "id": "cart-uuid",
                "lineItems": [{"id": "li-1", "quantity": 1}],
                "totalPrice": {"centAmount": 1500},
                "shippingAddress": {"key": "addr-1", "custom": {"fields": {"AddressReference": "ref-123"}}},
                "shippingCustomFields": {"fields": {"SelectedDeliveryType": "DIRECT"}},
            }

            requests_log = []
            adyen_payments_called = []

            async def _fake_request(method, url, params=None, json_body=None, **kwargs):
                requests_log.append((method, url, params, json_body))
                if url == "/webshop-cart-api/api/v4/cart":
                    return recalc_cart
                if "validatestock" in url:
                    return {}
                if "adyen/init" in url:
                    return {
                        "paymentId": "adyen-pid-777",
                        "adyenSessionResponse": {
                            "id": "CS12345",
                            "sessionData": "dummy-session-data",
                        },
                    }
                if "checkout/init" in url:
                    return {"status": "ok"}
                if "checkout/complete" in url:
                    return {"order": {"id": "order-cc-999", "orderNumber": "FP-CC-999"}}
                return {}

            client._request = _fake_request  # type: ignore[assignment]
            async def _fake_recalc_cart():
                return recalc_cart
            client.async_get_cart = _fake_recalc_cart  # type: ignore[assignment]

            class _FakeAdyenPostResponse:
                def __init__(self, data):
                    self._data = data
                    self.status = 200
                async def json(self):
                    return self._data
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass

            class _FakeSession:
                def post(self, url, json=None, **kwargs):
                    if "setup" in url:
                        return _FakeAdyenPostResponse({
                            "storedPaymentMethods": [
                                {
                                    "id": "card-id-123",
                                    "brand": "mastercard",
                                    "lastFour": "5678",
                                }
                            ]
                        })
                    if "payments" in url:
                        adyen_payments_called.append(json)
                        return _FakeAdyenPostResponse({"resultCode": "Authorised"})
                    return _FakeAdyenPostResponse({})

            client._session = _FakeSession()  # type: ignore[assignment]

            order = await client.async_place_order(
                payment_method=PAYMENT_CREDIT_CARD,
                stored_payment_id="card-id-123",
            )
            self.assertEqual(order["orderNumber"], "FP-CC-999")
            self.assertEqual(order["id"], "order-cc-999")

            # Verify Adyen payments payload used stored card
            self.assertEqual(len(adyen_payments_called), 1)
            pay_body = adyen_payments_called[0]
            self.assertEqual(pay_body["paymentMethod"]["storedPaymentMethodId"], "card-id-123")
            self.assertEqual(pay_body["paymentMethod"]["type"], "scheme")

            # Verify Flaschenpost checkout sequence
            url_seq = [r[1] for r in requests_log]
            self.assertTrue(any("validatestock" in u for u in url_seq))
            self.assertTrue(any("adyen/init" in u for u in url_seq))
            self.assertTrue(any("checkout/init" in u for u in url_seq))
            self.assertTrue(any("checkout/complete" in u for u in url_seq))

        asyncio.run(_run())

    def test_buy_cart_place_order_flow(self) -> None:
        async def _run() -> None:
            self.assertEqual(SERVICE_BUY_CART, "buy_cart")

            client = FlaschenpostApiClient(email="test@example.com", password="secret")
            client._cart_id = "cart-uuid"

            recalc_cart = {
                "id": "cart-uuid",
                "lineItems": [{"id": "li-1", "quantity": 2}],
                "totalPrice": {"centAmount": 2500},
                "shippingAddress": {"key": "", "custom": {"fields": {}}},
                "shippingCustomFields": {
                    "fields": {"SelectedDeliveryType": "DIRECT"}
                },
            }

            account_data = {
                "addresses": [
                    {
                        "key": "addr-key-1",
                        "custom": {
                            "fields": {
                                "AddressReference": "ref-12345",
                            }
                        },
                    }
                ]
            }

            requests_log = []

            async def _fake_request(method, url, params=None, json_body=None, **kwargs):
                requests_log.append((method, url, params, json_body))
                if url == "/webshop-cart-api/api/v4/cart":
                    return recalc_cart
                if "cart/actions" in url:
                    return recalc_cart
                if "validatestock" in url:
                    return {}
                if "payment/direct/init" in url:
                    return {
                        "paymentId": "pay-999",
                        "sessionId": "sess-888",
                        "userAuthorizeUrl": "https://api.flaschenpost.de/authorize/999",
                        "directDebitAccounts": [
                            {"ibanMasked": "DE**1234", "isBlackListed": False}
                        ],
                    }
                if "/authorize/999" in url:
                    return {"authorized": True}
                if "checkout/init" in url:
                    return {"status": "ok"}
                if "checkout/complete" in url:
                    return {
                        "order": {
                            "id": "order-111",
                            "orderNumber": "FP-123456",
                        }
                    }
                return {}

            client._request = _fake_request  # type: ignore[assignment]

            async def _fake_account():
                return account_data

            client.async_get_my_account = _fake_account  # type: ignore[assignment]

            # Test order placement with SEPA
            order = await client.async_place_order(
                payment_method=PAYMENT_SEPA,
                iban_last4="1234",
            )
            self.assertEqual(order.get("orderNumber"), "FP-123456")
            self.assertEqual(order["id"], "order-111")

            # Verify steps executed in sequence
            url_seq = [r[1] for r in requests_log]
            self.assertTrue(any("validatestock" in u for u in url_seq))
            self.assertTrue(any("payment/direct/init" in u for u in url_seq))
            self.assertTrue(any("/authorize/999" in u for u in url_seq))
            self.assertTrue(any("checkout/init" in u for u in url_seq))
            self.assertTrue(any("checkout/complete" in u for u in url_seq))

            # Verify shopperReferenceAdd received the fallback AddressReference
            init_call = next(r for r in requests_log if "payment/direct/init" in r[1])
            self.assertEqual(init_call[2]["shopperReferenceAdd"], "ref-12345")
            self.assertEqual(init_call[2]["ltkaid"], "addr-key-1")

        asyncio.run(_run())

    def test_lazy_multi_list_merge_and_cart_resolution(self) -> None:
        async def _run() -> None:
            fake_client = _FakeApiClient()
            mgr = FlaschenpostShoppingListManager(client=fake_client)  # type: ignore[arg-type]

            await mgr.async_save_named_list(
                "Every week",
                [
                    "1kg Naturjoghurt",
                    "1,5kg Puten Schnitzel",
                    "1 Kiste Pepsi Zero",
                    "500g Reis & Getreide::Milchreis",
                ],
            )
            await mgr.async_save_named_list(
                "Every even week",
                [
                    "1kg Karotten",
                    "500g Naturjoghurt",  # Should merge with 1kg -> 1500g (3 x 600g = 1800g)
                ],
            )

            # Lazy guarantee: ZERO API resolution calls when creating/saving shopping lists!
            self.assertEqual(len(fake_client.resolve_calls), 0)
            for it in mgr.get_list_items("Every week"):
                self.assertIsNone(it.article_id)

            # Now merge & resolve at add-to-cart time:
            res = await mgr.async_add_lists_to_cart(
                ["Every week", "Every even week"],
                clear_cart_first=True,
                mark_completed=False,
            )

            self.assertTrue(fake_client.cleared_cart)
            self.assertEqual(res["lists_merged"], ["Every week", "Every even week"])
            self.assertEqual(res["synced_count"], 5)

            # Recurring lists stay uncompleted when mark_completed=False
            self.assertTrue(
                all(not x.completed for x in mgr.get_list_items("Every week"))
            )

            pos_by_aid = {
                p["articleId"]: p["quantityTotal"]
                for p in fake_client.cart_positions_calls[0]
            }
            # 1kg + 500g = 1500g Naturjoghurt -> ceil(1500 / 600) = 3 packs (1.8kg)
            self.assertEqual(pos_by_aid[28242], 3)
            # 1,5kg Puten Schnitzel -> ceil(1500 / 500) = 3 packs (1.5kg)
            self.assertEqual(pos_by_aid[29997], 3)
            # 1 Kiste Pepsi Zero -> 1 crate
            self.assertEqual(pos_by_aid[1838], 1)
            # 500g Reis & Getreide::Milchreis -> Dry rice #10495 (2 x 400g = 800g), NOT dairy #7963
            self.assertEqual(pos_by_aid[10495], 2)
            self.assertNotIn(7963, pos_by_aid)
            # 1kg Karotten -> 1x 1kg Möhren
            self.assertEqual(pos_by_aid[30399], 1)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
