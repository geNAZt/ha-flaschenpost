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

if "voluptuous" not in sys.modules:
    vol = types.ModuleType("voluptuous")
    vol.Required = lambda k, **kw: k
    vol.Optional = lambda k, **kw: k
    vol.Any = lambda *args: None
    vol.All = lambda *args: None
    vol.Coerce = lambda t: t
    vol.Range = lambda **kw: None
    sys.modules["voluptuous"] = vol

if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    ha_core = types.ModuleType("homeassistant.core")
    ha_core.HomeAssistant = object
    ha_comp = types.ModuleType("homeassistant.components")
    ha_ws = types.ModuleType("homeassistant.components.websocket_api")

    def _ws_cmd(schema: Any) -> Any:
        def dec(fn: Any) -> Any:
            fn._ws_schema = schema
            return fn
        return dec

    ha_ws.websocket_command = _ws_cmd
    ha_ws.async_response = lambda fn: fn
    ha_ws.ActiveConnection = object
    ha_ws.async_register_command = lambda hass, cmd: None
    ha_comp.websocket_api = ha_ws
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.components"] = ha_comp
    sys.modules["homeassistant.components.websocket_api"] = ha_ws

if "custom_components.flaschenpost" not in sys.modules:
    cc_pkg = types.ModuleType("custom_components")
    cc_pkg.__path__ = [str(_ROOT / "custom_components")]
    fp_pkg = types.ModuleType("custom_components.flaschenpost")
    fp_pkg.__path__ = [str(_PKG_DIR)]
    sys.modules.setdefault("custom_components", cc_pkg)
    sys.modules["custom_components.flaschenpost"] = fp_pkg
    for mod_name in ("const", "api", "shopping_list", "websocket_api"):
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
    extract_negative_keywords,
    extract_product_categories,
    extract_product_summary,
    matches_category_filter,
    matches_query_qualifiers,
    normalize_search_queries,
    parse_price_per_unit_text,
    product_matches_negative_keywords,
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
    ShoppingListItem,
    build_pinned_spec_summary,
    build_preview_spec,
    estimate_candidate_pack_plan,
    format_shopping_item_summary,
    format_shopping_spec_summary,
    parse_shopping_item_details,
    parse_shopping_item_spec,
    parse_shopping_item_summary,
)
from custom_components.flaschenpost.websocket_api import (
    async_register_websocket_commands,
    ws_add_item,
    ws_buy_cart,
    ws_delete_item,
    ws_delete_list,
    ws_get_cart,
    ws_get_categories,
    ws_get_lists,
    ws_preview_lists,
    ws_preview_search,
    ws_save_list,
    ws_sync_to_cart,
    ws_update_item,
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
        if "heidelbeeren" in ql:
            cand_29010 = {
                "article_id": 29010,
                "name": "K-Classic Heidelbeeren gezuckert",
                "description": "540g",
                "package_weight_g": 540.0,
                "price_eur": 2.29,
                "price_per_kg_eur": 4.24,
                "is_available": True,
                "categories": ["Obst- & Gemüsekonserven", "Beeren"],
                "category_slugs": ["obst-gemuesekonserven", "beeren"],
            }
            cand_32672 = {
                "article_id": 32672,
                "name": "K-Classic Heidelbeeren",
                "description": "750g",
                "package_weight_g": 750.0,
                "price_eur": 4.89,
                "price_per_kg_eur": 6.52,
                "is_available": True,
                "categories": ["Tiefkühl", "Obst"],
                "category_slugs": ["tiefkuehl", "obst"],
            }
            res = [cand_29010, cand_32672]
            _clean_q, extracted_neg = extract_negative_keywords(query)
            eff_neg = list(
                dict.fromkeys(
                    [k.lower() for k in (kwargs.get("negative_keywords") or []) + extracted_neg]
                )
            )
            if eff_neg:
                res = [c for c in res if not product_matches_negative_keywords(c, eff_neg)]
            return res[:limit]
        if "joghurt" in ql:
            cand_28249 = {
                "article_id": 28249,
                "name": "K-Classic Naturjoghurt 3,5%",
                "description": "4 x 150g",
                "package_weight_g": 600.0,
                "price_eur": 0.89,
                "price_per_kg_eur": 1.48,
                "is_available": True,
                "categories": ["Joghurt & Skyr", "Naturjoghurt", "Eier & Molkerei"],
                "category_slugs": ["joghurt-skyr", "naturjoghurt"],
            }
            cand_28435 = {
                "article_id": 28435,
                "name": "K-Classic Naturjoghurt 1,5%",
                "description": "500g",
                "package_weight_g": 500.0,
                "price_eur": 0.79,
                "price_per_kg_eur": 1.58,
                "is_available": True,
                "categories": ["Joghurt & Skyr", "Naturjoghurt", "Eier & Molkerei"],
                "category_slugs": ["joghurt-skyr", "naturjoghurt"],
            }
            res = [cand_28249, cand_28435]
            if category:
                res = [c for c in res if matches_category_filter(c, category)]
            return res[:limit]
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
        negative_keywords: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        self.resolve_calls.append((query, category, unit_type, target_amount_base))
        ql = query.lower()
        if "heidelbeeren" in ql:
            __clean_q, extracted_neg = extract_negative_keywords(query)
            eff_neg = list(
                dict.fromkeys(
                    [k.lower() for k in (negative_keywords or []) + extracted_neg]
                )
            )
            has_zucker_neg = any("zucker" in k for k in eff_neg)
            if has_zucker_neg:
                return {
                    "article_id": 32672,
                    "quantity": 1,
                    "unit_type": unit_type,
                    "requested_amount_base": target_amount_base,
                    "delivered_amount_base": 750.0,
                    "line_total_eur": 4.89,
                    "product": {
                        "article_id": 32672,
                        "name": "K-Classic Heidelbeeren",
                        "description": "750g",
                        "package_weight_g": 750.0,
                        "categories": ["Tiefkühl", "Obst"],
                        "price_eur": 4.89,
                        "price_per_kg_eur": 6.52,
                    },
                }
            return {
                "article_id": 29010,
                "quantity": 1,
                "unit_type": unit_type,
                "requested_amount_base": target_amount_base,
                "delivered_amount_base": 540.0,
                "line_total_eur": 2.29,
                "product": {
                    "article_id": 29010,
                    "name": "K-Classic Heidelbeeren gezuckert",
                    "description": "540g",
                    "package_weight_g": 540.0,
                    "categories": ["Obst- & Gemüsekonserven", "Beeren"],
                    "price_eur": 2.29,
                    "price_per_kg_eur": 4.24,
                },
            }
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
            if sort_by == SORT_PRICE_PER_KG:
                pkg_g = 600.0
                qty = (
                    max(1, math.ceil(target_amount_base / pkg_g - 1e-9))
                    if unit_type == UNIT_TYPE_WEIGHT_G
                    else max(1, round(target_amount_base))
                )
                return {
                    "article_id": 28249,
                    "quantity": qty,
                    "unit_type": unit_type,
                    "requested_amount_base": target_amount_base,
                    "delivered_amount_base": qty * pkg_g,
                    "line_total_eur": round(qty * 0.89, 2),
                    "product": {
                        "article_id": 28249,
                        "name": "K-Classic Naturjoghurt 3,5%",
                        "description": "4 x 150g",
                        "package_weight_g": 600.0,
                        "price_eur": 0.89,
                        "price_per_kg_eur": 1.48,
                    },
                }
            # Default / total price: 500g @ 0.79 EUR -> 2 packs = 1000g for 1.58 EUR beats 2 x 0.89 = 1.78 EUR!
            pkg_g = 500.0
            qty = (
                max(1, math.ceil(target_amount_base / pkg_g - 1e-9))
                if unit_type == UNIT_TYPE_WEIGHT_G
                else max(1, round(target_amount_base))
            )
            return {
                "article_id": 28435,
                "quantity": qty,
                "unit_type": unit_type,
                "requested_amount_base": target_amount_base,
                "delivered_amount_base": qty * pkg_g,
                "line_total_eur": round(qty * 0.79, 2),
                "product": {
                    "article_id": 28435,
                    "name": "K-Classic Naturjoghurt 1,5%",
                    "description": "500g",
                    "package_weight_g": 500.0,
                    "price_eur": 0.79,
                    "price_per_kg_eur": 1.58,
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
        return {
            "id": "cart-123",
            "totalPrice": {"centAmount": 2850},
            "shippingInfo": {"price": {"centAmount": 0}},
            "custom": {"fields": {"MinimumOrderValue": 2500}},
            "lineItems": [
                {
                    "variant": {"sku": "32672"},
                    "product": {"name": {"de": "K-Classic Heidelbeeren"}},
                    "quantity": 1,
                    "price": {"value": {"centAmount": 489}},
                }
            ],
        }

    async def async_place_order(self, **kwargs: Any) -> dict[str, Any]:
        return {"id": "ord-mock-123", "orderNumber": "10042"}

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
            # 1kg + 500g = 1500g Naturjoghurt -> ceil(1500 / 500) = 3 packs (1.5kg) via total price #28435
            self.assertEqual(pos_by_aid[28435], 3)
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



    def test_total_price_winner_and_sort_switching(self) -> None:
            """Verify #28435 (1.58 EUR total) wins over #28249 (1.78 EUR total) for 1kg yogurt by default."""
            async def _run() -> None:
                fake_client = _FakeApiClient()
                mgr = FlaschenpostShoppingListManager(client=fake_client)  # type: ignore[arg-type]

                # Default (total price): #28435 should win
                preview_default = await mgr.async_preview_search(
                    "Naturjoghurt",
                    amount_prefix="1kg",
                    category="Joghurt & Skyr > Naturjoghurt",
                )
                self.assertIsNotNone(preview_default["winner"])
                self.assertEqual(preview_default["winner"]["article_id"], 28435)
                self.assertEqual(preview_default["winner"]["line_total_eur"], 1.58)
                # In candidate table, #28435 is first because 1.58 EUR < 1.78 EUR
                self.assertEqual(preview_default["candidates"][0]["article_id"], 28435)
                self.assertEqual(preview_default["candidates"][1]["article_id"], 28249)
                self.assertIn("1.58 EUR", preview_default["markdown"])

                # Sort by €/kg: #28249 should win (1.48 EUR/kg vs 1.58 EUR/kg)
                preview_kg = await mgr.async_preview_search(
                    "Naturjoghurt",
                    amount_prefix="1kg",
                    category="Joghurt & Skyr > Naturjoghurt",
                    sort_by=SORT_PRICE_PER_KG,
                )
                self.assertIsNotNone(preview_kg["winner"])
                self.assertEqual(preview_kg["winner"]["article_id"], 28249)
                self.assertEqual(preview_kg["winner"]["line_total_eur"], 1.78)
                self.assertEqual(preview_kg["candidates"][0]["article_id"], 28249)

                # Test real FlaschenpostApiClient resolution logic with mock products
                real_client = FlaschenpostApiClient(email="test@example.com", password="pass")
                cands = [
                    {
                        "article_id": 28249,
                        "name": "K-Classic Naturjoghurt 3,5%",
                        "description": "4 x 150g",
                        "package_weight_g": 600.0,
                        "price_eur": 0.89,
                        "price_per_kg_eur": 1.48,
                        "is_available": True,
                    },
                    {
                        "article_id": 28435,
                        "name": "K-Classic Naturjoghurt 1,5%",
                        "description": "500g",
                        "package_weight_g": 500.0,
                        "price_eur": 0.79,
                        "price_per_kg_eur": 1.58,
                        "is_available": True,
                    },
                ]
                async def _fake_search(*args, **kwargs):
                    return list(cands)
                real_client.async_search_products = _fake_search  # type: ignore[assignment]

                # Default (None / SORT_PRICE): #28435 wins
                res_default = await real_client.async_resolve_item_for_cart(
                    "Naturjoghurt",
                    unit_type=UNIT_TYPE_WEIGHT_G,
                    target_amount_base=1000.0,
                )
                self.assertIsNotNone(res_default)
                self.assertEqual(res_default["article_id"], 28435)
                self.assertEqual(res_default["line_total_eur"], 1.58)

                # Explicit SORT_PRICE_PER_KG: #28249 wins
                res_kg = await real_client.async_resolve_item_for_cart(
                    "Naturjoghurt",
                    unit_type=UNIT_TYPE_WEIGHT_G,
                    target_amount_base=1000.0,
                    sort_by=SORT_PRICE_PER_KG,
                )
                self.assertIsNotNone(res_kg)
                self.assertEqual(res_kg["article_id"], 28249)
                self.assertEqual(res_kg["line_total_eur"], 1.78)

            asyncio.run(_run())


    def test_negative_keywords_filtering_and_resolution(self) -> None:
        """Verify negative keyword extraction, candidate filtering, and cart resolution.

        Specifically 'Heidelbeeren !zucker' should match 'K-Classic Heidelbeeren' (#32672)
        and exclude 'K-Classic Heidelbeeren gezuckert' (#29010).
        """
        # 1. Negative keyword extraction
        cleaned, negs = extract_negative_keywords("Heidelbeeren !zucker")
        self.assertEqual(cleaned, "Heidelbeeren")
        self.assertEqual(negs, ["zucker"])

        cleaned2, negs2 = extract_negative_keywords("500g Heidelbeeren !zucker !bio")
        self.assertEqual(cleaned2, "500g Heidelbeeren")
        self.assertEqual(negs2, ["zucker", "bio"])

        cleaned3, negs3 = extract_negative_keywords("Obst & Gemüse::Heidelbeeren !zucker")
        self.assertEqual(cleaned3, "Obst & Gemüse::Heidelbeeren")
        self.assertEqual(negs3, ["zucker"])

        cleaned4, negs4 = extract_negative_keywords("Heidelbeeren -zucker")
        self.assertEqual(cleaned4, "Heidelbeeren")
        self.assertEqual(negs4, ["zucker"])

        # 2. Spec parsing and summary formatting
        spec = parse_shopping_item_spec("Heidelbeeren !zucker")
        self.assertEqual(spec.query, "Heidelbeeren")
        self.assertEqual(spec.negative_keywords, ["zucker"])
        self.assertEqual(format_shopping_spec_summary(spec), "Heidelbeeren !zucker")

        spec_kg = parse_shopping_item_spec("500g Heidelbeeren !zucker")
        self.assertEqual(spec_kg.query, "Heidelbeeren")
        self.assertEqual(spec_kg.negative_keywords, ["zucker"])
        self.assertEqual(format_shopping_spec_summary(spec_kg), "500g Heidelbeeren !zucker")

        # 3. Product negative keywords matching
        cand_gezuckert = {
            "name": "K-Classic Heidelbeeren gezuckert",
            "description": "540g",
            "categories": ["Obst- & Gemüsekonserven", "Beeren"],
        }
        cand_pure = {
            "name": "K-Classic Heidelbeeren",
            "description": "750g",
            "categories": ["Tiefkühl", "Obst"],
        }
        self.assertTrue(product_matches_negative_keywords(cand_gezuckert, ["zucker"]))
        self.assertFalse(product_matches_negative_keywords(cand_pure, ["zucker"]))

        async def _run() -> None:
            fake_client = _FakeApiClient()
            mgr = FlaschenpostShoppingListManager(client=fake_client)  # type: ignore[arg-type]

            # Without negative keyword: #29010 ("gezuckert") is cheaper (2.29 EUR vs 4.89 EUR) and wins
            preview_unfiltered = await mgr.async_preview_search("Heidelbeeren")
            self.assertIsNotNone(preview_unfiltered["winner"])
            self.assertEqual(preview_unfiltered["winner"]["article_id"], 29010)

            # With negative keyword "!zucker": #29010 is excluded, #32672 wins!
            preview_filtered = await mgr.async_preview_search("Heidelbeeren !zucker")
            self.assertIsNotNone(preview_filtered["winner"])
            self.assertEqual(preview_filtered["winner"]["article_id"], 32672)
            cand_ids = [c["article_id"] for c in preview_filtered["candidates"]]
            self.assertIn(32672, cand_ids)
            self.assertNotIn(29010, cand_ids)

            # Test real FlaschenpostApiClient search filtering logic
            real_client = FlaschenpostApiClient(email="test@example.com", password="pass")

            real_client.async_get_cart = lambda: asyncio.sleep(0, result={"id": "cart-1"})  # type: ignore[assignment]
            real_client._warehouse_id = 123
            real_client._client_ready = asyncio.Event()
            real_client._client_ready.set()

            async def _fake_request(method: str, path: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
                return {
                    "results": [
                        {
                            "id": "p-29010",
                            "name": {"de": "K-Classic Heidelbeeren gezuckert"},
                            "categories": [{"obj": {"name": {"de": "Obst- & Gemüsekonserven"}}}],
                            "masterVariant": {
                                "sku": "29010",
                                "prices": [{"value": {"centAmount": 229}}],
                                "attributes": [
                                    {"name": "PriceFields", "value": '{"Price": 229, "BasePrice": "4,24 € / kg", "ArticleStatus": "A"}'},
                                    {"name": "ShortDescription", "value": "540g"},
                                ],
                            },
                        },
                        {
                            "id": "p-32672",
                            "name": {"de": "K-Classic Heidelbeeren"},
                            "categories": [{"obj": {"name": {"de": "Tiefkühl"}}}],
                            "masterVariant": {
                                "sku": "32672",
                                "prices": [{"value": {"centAmount": 489}}],
                                "attributes": [
                                    {"name": "PriceFields", "value": '{"Price": 489, "BasePrice": "6,52 € / kg", "ArticleStatus": "A"}'},
                                    {"name": "ShortDescription", "value": "750g"},
                                ],
                            },
                        },
                    ]
                }
            real_client._request = _fake_request  # type: ignore[assignment]

            filtered_search = await real_client.async_search_products(
                "Heidelbeeren !zucker",
                only_available=False,
            )
            filtered_ids = [c["article_id"] for c in filtered_search]
            self.assertEqual(filtered_ids, [32672])

            resolved_winner = await real_client.async_resolve_item_for_cart("Heidelbeeren !zucker")
            self.assertIsNotNone(resolved_winner)
            self.assertEqual(resolved_winner["article_id"], 32672)
            await real_client.async_close()

            # Test shopping list persistence and round-trip
            item = mgr._build_lazy_item("Heidelbeeren !zucker")
            self.assertEqual(item.query, "Heidelbeeren")
            self.assertEqual(item.negative_keywords, ["zucker"])
            serialized = item.to_dict()
            self.assertEqual(serialized["negative_keywords"], ["zucker"])
            deserialized = ShoppingListItem.from_dict(serialized)
            self.assertEqual(deserialized.negative_keywords, ["zucker"])
            self.assertEqual(deserialized.query, "Heidelbeeren")

            # Test list merge & cart resolution
            await mgr.async_add_item("Heidelbeeren !zucker")
            add_res = await mgr.async_add_lists_to_cart()
            self.assertEqual(add_res["synced_count"], 1)
            self.assertEqual(add_res["resolved_items"][0]["article_id"], 32672)

        asyncio.run(_run())


    def test_websocket_api_endpoints_and_panel_registration(self) -> None:
        """Verify all WebSocket API commands for the interactive shopping list panel."""
        class _MockActiveConn:
            def __init__(self) -> None:
                self.results: dict[int, Any] = {}
                self.errors: dict[int, tuple[str, str]] = {}

            def send_result(self, msg_id: int, result: Any = None) -> None:
                self.results[msg_id] = result

            def send_error(self, msg_id: int, code: str, message: str) -> None:
                self.errors[msg_id] = (code, message)

        class _MockEntry:
            options: dict[str, Any] = {}
            data: dict[str, Any] = {"default_payment_method": "credit_card"}

        class _MockCoordinator:
            def __init__(self, fake_client: _FakeApiClient, mgr: FlaschenpostShoppingListManager) -> None:
                self.client = fake_client
                self.shopping_list = mgr
                self.config_entry = _MockEntry()
                self.updated_listeners = False
                self.refreshed = False

            def async_update_listeners(self) -> None:
                self.updated_listeners = True

            async def async_request_refresh(self) -> None:
                self.refreshed = True

        async def _run() -> None:
            fake_client = _FakeApiClient()
            mgr = FlaschenpostShoppingListManager(client=fake_client)  # type: ignore[arg-type]
            coord = _MockCoordinator(fake_client, mgr)

            mock_hass = types.SimpleNamespace()
            mock_hass.data = {"flaschenpost": {"mock_entry": coord}}
            registered_cmds: list[Any] = []
            sys.modules["homeassistant.components.websocket_api"].async_register_command = (  # type: ignore[attr-defined]
                lambda hass, cmd: registered_cmds.append(cmd)
            )

            # Test command registration
            async_register_websocket_commands(mock_hass)  # type: ignore[arg-type]
            self.assertEqual(len(registered_cmds), 12)

            conn = _MockActiveConn()

            # 1. ws_get_lists
            await ws_get_lists(mock_hass, conn, {"id": 1, "type": "flaschenpost/get_lists"})  # type: ignore[arg-type]
            self.assertIn(1, conn.results)
            self.assertTrue(any("Shopping list" in n or "Einkaufsliste" in n for n in conn.results[1]["names"]))

            # 2. ws_save_list
            await ws_save_list(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 2,
                    "type": "flaschenpost/save_list",
                    "name": "Wocheneinkauf",
                    "items": ["500g Heidelbeeren !zucker", "1 Kiste Pepsi Zero"],
                },
            )
            self.assertIn(2, conn.results)
            self.assertEqual(conn.results[2]["name"], "Wocheneinkauf")
            self.assertEqual(conn.results[2]["item_count"], 2)
            self.assertIn("Wocheneinkauf", conn.results[2]["names"])

            # 3. ws_add_item
            await ws_add_item(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 3,
                    "type": "flaschenpost/add_item",
                    "list_name": "Wocheneinkauf",
                    "summary": "1kg Naturjoghurt [€/kg]",
                },
            )
            self.assertIn(3, conn.results)
            self.assertEqual(conn.results[3]["item"]["query"], "Naturjoghurt")

            # 4. ws_update_item
            item_uid = conn.results[3]["item"]["uid"]
            await ws_update_item(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 4,
                    "type": "flaschenpost/update_item",
                    "list_name": "Wocheneinkauf",
                    "uid": item_uid,
                    "completed": True,
                },
            )
            self.assertIn(4, conn.results)
            self.assertTrue(conn.results[4]["item"]["completed"])

            # 5. ws_delete_item
            await ws_delete_item(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 5,
                    "type": "flaschenpost/delete_item",
                    "list_name": "Wocheneinkauf",
                    "uids": [item_uid],
                },
            )
            self.assertIn(5, conn.results)
            self.assertEqual(conn.results[5]["deleted_uids"], [item_uid])

            # 6. ws_preview_search with negative keywords
            await ws_preview_search(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 6,
                    "type": "flaschenpost/preview_search",
                    "query": "Heidelbeeren !zucker",
                },
            )
            self.assertIn(6, conn.results)
            res_preview = conn.results[6]
            self.assertIsNotNone(res_preview["winner"])
            self.assertEqual(res_preview["winner"]["article_id"], 32672)
            cand_aids = [c["article_id"] for c in res_preview["candidates"]]
            self.assertIn(32672, cand_aids)
            self.assertNotIn(29010, cand_aids)

            # 7. ws_preview_lists (dry run)
            await ws_preview_lists(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 7,
                    "type": "flaschenpost/preview_lists",
                    "shopping_lists": ["Wocheneinkauf"],
                },
            )
            self.assertIn(7, conn.results)
            self.assertIn("estimated_goods_eur", conn.results[7])

            # 8. ws_get_categories
            await ws_get_categories(mock_hass, conn, {"id": 8, "type": "flaschenpost/get_categories"})  # type: ignore[arg-type]
            self.assertIn(8, conn.results)
            self.assertIsInstance(conn.results[8]["options"], list)

            # 9. ws_get_cart
            await ws_get_cart(mock_hass, conn, {"id": 9, "type": "flaschenpost/get_cart"})  # type: ignore[arg-type]
            self.assertIn(9, conn.results)
            self.assertIn("min_order_value_eur", conn.results[9])

            # 10. ws_sync_to_cart
            await ws_sync_to_cart(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 10,
                    "type": "flaschenpost/sync_to_cart",
                    "shopping_lists": ["Wocheneinkauf"],
                },
            )
            self.assertIn(10, conn.results)
            self.assertTrue(coord.refreshed)

            # 11. ws_buy_cart: unconfirmed error
            await ws_buy_cart(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 11,
                    "type": "flaschenpost/buy_cart",
                    "confirm": False,
                },
            )
            self.assertIn(11, conn.errors)
            self.assertEqual(conn.errors[11][0], "unconfirmed")

            # 12. ws_buy_cart: confirmed
            await ws_buy_cart(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 12,
                    "type": "flaschenpost/buy_cart",
                    "confirm": True,
                },
            )
            self.assertIn(12, conn.results)
            self.assertEqual(conn.results[12]["order_id"], "ord-mock-123")

            # 13. ws_delete_list
            await ws_delete_list(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 13,
                    "type": "flaschenpost/delete_list",
                    "name": "Wocheneinkauf",
                },
            )
            self.assertIn(13, conn.results)
            self.assertTrue(conn.results[13]["deleted"])

            # 14. Verify frontend panel JS asset exists and contains web component
            panel_js_file = _PKG_DIR / "frontend" / "flaschenpost-panel.js"
            self.assertTrue(panel_js_file.exists())
            js_content = panel_js_file.read_text(encoding="utf-8")
            self.assertIn("flaschenpost-panel", js_content)
            self.assertIn("flaschenpost-card", js_content)
            self.assertIn("flaschenpost-view", js_content)

        asyncio.run(_run())

if __name__ == "__main__":
    unittest.main()
