"""Unit tests for Flaschenpost API helpers, category filters, interactive preview, and lazy resolution."""

from __future__ import annotations

import asyncio
import importlib.util
import math
import sys
import types
import unittest
from datetime import UTC, datetime, timedelta
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
    vol.In = lambda *args: None
    sys.modules["voluptuous"] = vol

if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    ha_core = types.ModuleType("homeassistant.core")
    ha_core.HomeAssistant = object
    ha_core.callback = lambda fn: fn
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

    def _mock_parse_dt(s: str | None) -> datetime | None:
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)

    ha_util = types.ModuleType("homeassistant.util")
    ha_dt = types.ModuleType("homeassistant.util.dt")
    ha_dt.utcnow = lambda: datetime(2026, 11, 4, 14, 0, 0, tzinfo=UTC)
    ha_dt.now = lambda: datetime(2026, 11, 4, 14, 0, 0, tzinfo=UTC)
    ha_dt.parse_datetime = _mock_parse_dt
    ha_dt.as_local = lambda dt: dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    ha_util.dt = ha_dt
    sys.modules["homeassistant.util"] = ha_util
    sys.modules["homeassistant.util.dt"] = ha_dt

    ha_cfg = types.ModuleType("homeassistant.config_entries")
    ha_cfg.ConfigEntry = object
    sys.modules["homeassistant.config_entries"] = ha_cfg

    ha_exc = types.ModuleType("homeassistant.exceptions")
    ha_exc.ConfigEntryAuthFailed = Exception
    sys.modules["homeassistant.exceptions"] = ha_exc

    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_coord = types.ModuleType("homeassistant.helpers.update_coordinator")
    class DataUpdateCoordinator:
        def __init__(self, hass: Any, logger: Any, name: str, update_interval: Any = None) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.last_update_success = True
            self.data: Any = None
        def __class_getitem__(cls, item: Any) -> Any:
            return cls
        async def async_request_refresh(self) -> None:
            pass
    class CoordinatorEntity:
        def __init__(self, coordinator: Any, *args: Any, **kwargs: Any) -> None:
            self.coordinator = coordinator
        def __class_getitem__(cls, item: Any) -> Any:
            return cls
    ha_coord.DataUpdateCoordinator = DataUpdateCoordinator
    ha_coord.UpdateFailed = Exception
    ha_coord.CoordinatorEntity = CoordinatorEntity
    ha_helpers.update_coordinator = ha_coord
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.update_coordinator"] = ha_coord

    ha_sensor = types.ModuleType("homeassistant.components.sensor")
    class SensorEntity:
        pass
    class SensorDeviceClass:
        TIMESTAMP = "timestamp"
        MONETARY = "monetary"
    class SensorStateClass:
        MEASUREMENT = "measurement"
        TOTAL = "total"
    ha_sensor.SensorEntity = SensorEntity
    ha_sensor.SensorDeviceClass = SensorDeviceClass
    ha_sensor.SensorStateClass = SensorStateClass
    ha_comp.sensor = ha_sensor
    sys.modules["homeassistant.components.sensor"] = ha_sensor

    ha_button = types.ModuleType("homeassistant.components.button")
    class ButtonEntity:
        pass
    ha_button.ButtonEntity = ButtonEntity
    ha_comp.button = ha_button
    sys.modules["homeassistant.components.button"] = ha_button

    ha_event = types.ModuleType("homeassistant.components.event")
    class EventEntity:
        _attr_event_types: list[str] = []
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._last_event_type: str | None = None
            self._last_event_attributes: dict[str, Any] | None = None
        def _trigger_event(self, event_type: str, event_attributes: Any = None) -> None:
            self._last_event_type = event_type
            self._last_event_attributes = event_attributes
        def async_write_ha_state(self) -> None:
            pass
    ha_event.EventEntity = EventEntity
    ha_comp.event = ha_event
    sys.modules["homeassistant.components.event"] = ha_event

    ha_const = types.ModuleType("homeassistant.const")
    ha_const.CURRENCY_EURO = "€"
    sys.modules["homeassistant.const"] = ha_const

    ha_dev = types.ModuleType("homeassistant.helpers.device_registry")
    class DeviceInfo(dict):
        pass
    class DeviceEntryType:
        SERVICE = "service"
    ha_dev.DeviceInfo = DeviceInfo
    ha_dev.DeviceEntryType = DeviceEntryType
    ha_helpers.device_registry = ha_dev
    sys.modules["homeassistant.helpers.device_registry"] = ha_dev

    ha_ep = types.ModuleType("homeassistant.helpers.entity_platform")
    ha_ep.AddEntitiesCallback = object
    ha_helpers.entity_platform = ha_ep
    sys.modules["homeassistant.helpers.entity_platform"] = ha_ep

if "custom_components.flaschenpost" not in sys.modules:
    cc_pkg = types.ModuleType("custom_components")
    cc_pkg.__path__ = [str(_ROOT / "custom_components")]
    fp_pkg = types.ModuleType("custom_components.flaschenpost")
    fp_pkg.__path__ = [str(_PKG_DIR)]
    sys.modules.setdefault("custom_components", cc_pkg)
    sys.modules["custom_components.flaschenpost"] = fp_pkg
    for mod_name in ("const", "api", "shopping_list", "storage", "coordinator", "entity", "sensor", "button", "event", "websocket_api"):
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
    compute_optimal_pack_plan,
    extract_negative_keywords,
    extract_price_tiers,
    extract_product_categories,
    extract_product_summary,
    matches_category_filter,
    matches_query_qualifiers,
    normalize_search_queries,
    parse_price_per_unit_text,
    product_matches_negative_keywords,
)
from custom_components.flaschenpost.button import FlaschenpostRefreshButton
from custom_components.flaschenpost.const import (
    CONF_DEFAULT_PAYMENT,
    CONF_DELIVERY_LOCATION,
    CONF_IBAN_LAST4,
    CONF_STORED_PAYMENT_ID,
    CONF_WAREHOUSE_ID,
    DEFAULT_SHOPPING_LIST_NAME,
    PAYMENT_CREDIT_CARD,
    PAYMENT_PAYPAL,
    PAYMENT_SEPA,
    SERVICE_GET_PAYMENT_METHODS,
    SERVICE_GET_STORED_PAYMENT_ID,
    SERVICE_PLACE_ORDER,
    SORT_PRICE_PER_KG,
    SORT_PRICE_PER_UNIT,
    UNIT_TYPE_CRATE,
    UNIT_TYPE_UNIT,
    UNIT_TYPE_WEIGHT_G,
)
from custom_components.flaschenpost.coordinator import (
    FlaschenpostCoordinator,
    FlaschenpostSnapshot,
    async_resolve_payment_parameters,
)
from custom_components.flaschenpost.event import (
    FlaschenpostListItemConsumedEventEntity,
    async_setup_entry as async_setup_event_entry,
)
from custom_components.flaschenpost.sensor import (
    FlaschenpostCartTotalSensor,
    FlaschenpostLastUpdateSensor,
    FlaschenpostListMonthlySpentSensor,
    FlaschenpostListTotalSpentSensor,
    FlaschenpostListWeeklySpentSensor,
    FlaschenpostListYearlySpentSensor,
    FlaschenpostMonthlySpentSensor,
    FlaschenpostNextUpdateSensor,
    FlaschenpostTotalSpentSensor,
    FlaschenpostWeeklySpentSensor,
    FlaschenpostYearlySpentSensor,
    async_setup_entry as async_setup_sensor_entry,
)
from custom_components.flaschenpost.shopping_list import (
    DEFAULT_ITEM_WEIGHT,
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
from custom_components.flaschenpost.storage import FlaschenpostSqliteStorage
from custom_components.flaschenpost.websocket_api import (
    async_register_websocket_commands,
    ws_add_coupon,
    ws_add_item,
    ws_buy_cart,
    ws_delete_coupon,
    ws_delete_item,
    ws_delete_list,
    ws_get_cart,
    ws_get_categories,
    ws_get_coupons,
    ws_get_lists,
    ws_get_stored_payment_id,
    ws_import_cart_to_list,
    ws_place_order,
    ws_preview_lists,
    ws_preview_search,
    ws_refresh,
    ws_reset_list_weights,
    ws_save_list,
    ws_set_list_config,
    ws_sync_to_cart,
    ws_update_item,
)


class _FakeApiClient:
    """Stub client verifying lazy cart-time resolution, category filters, weight math, and crate filtering."""

    def __init__(self) -> None:
        self.cart_positions_calls: list[list[dict[str, int]]] = []
        self.resolve_calls: list[tuple[str, str | None, str, float]] = []
        self.cleared_cart: bool = False
        self.applied_discount_codes: list[str] = []
        self.past_orders_data: list[dict[str, Any]] = []

    async def async_get_past_orders(
        self, days: int = 365 * 3, offset: int = 0
    ) -> dict[str, Any]:
        return {
            "results": self.past_orders_data[offset : offset + 20],
            "total": len(self.past_orders_data),
        }

    async def async_get_all_past_orders(
        self, days: int = 365 * 3
    ) -> list[dict[str, Any]]:
        return list(self.past_orders_data)

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
            if category:
                res = [c for c in res if matches_category_filter(c, category)]
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
        if article_id is not None:
            qty = max(1, round(target_amount_base))
            return {
                "article_id": int(article_id),
                "quantity": qty,
                "unit_type": unit_type,
                "requested_amount_base": target_amount_base,
                "delivered_amount_base": float(qty),
                "line_total_eur": round(qty * 2.50, 2),
                "product": {
                    "article_id": int(article_id),
                    "name": query,
                    "description": "1x",
                    "price_eur": 2.50,
                },
            }
        ql = query.lower()
        if "heidelbeeren" in ql:
            __clean_q, extracted_neg = extract_negative_keywords(query)
            eff_neg = list(
                dict.fromkeys(
                    [k.lower() for k in (negative_keywords or []) + extracted_neg]
                )
            )
            has_zucker_neg = any("zucker" in k for k in eff_neg)
            is_tk = bool(category and "tiefk" in category.lower())
            if has_zucker_neg or is_tk:
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

    async def async_get_saved_payment_methods(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "credit_card:sp-99",
                "payment_method": "credit_card",
                "stored_payment_id": "sp-99",
                "brand": "visa",
                "last4": "4242",
                "label": "Kreditkarte VISA •••• 4242",
            }
        ]

    async def async_add_discount_code(self, code: str) -> dict[str, Any]:
        self.applied_discount_codes.append(code)
        return {"id": "cart-123"}

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

        herta_summary = {
            "name": "Herta Finesse Putenbrust gegrillt",
            "categories": [
                "Fleisch & Fisch",
                "Wurst & Aufschnitt",
                "Geflügelaufschnitt",
            ],
            "category_slugs": [
                "fleisch-fisch",
                "wurst-aufschnitt",
                "gefluegelaufschnitt",
            ],
        }
        meat_summary = {
            "name": "K-Purland Puten Hackfleisch",
            "categories": ["Fleisch & Fisch", "Fleisch"],
            "category_slugs": ["fleisch-fisch", "fleisch"],
        }
        # Filter "Fleisch & Fisch -> Fleisch" rejects Wurst & Aufschnitt
        self.assertFalse(
            matches_category_filter(herta_summary, "Fleisch & Fisch -> Fleisch")
        )
        self.assertFalse(
            matches_category_filter(herta_summary, "Fleisch & Fisch::Fleisch")
        )
        self.assertTrue(
            matches_category_filter(meat_summary, "Fleisch & Fisch -> Fleisch")
        )
        self.assertTrue(
            matches_category_filter(meat_summary, "Fleisch & Fisch::Fleisch")
        )
        # Filter "Fleisch" matches pure meat, but rejects Wurst & Aufschnitt
        self.assertFalse(matches_category_filter(herta_summary, "Fleisch"))
        self.assertTrue(matches_category_filter(meat_summary, "Fleisch"))
        # Filter "Fleisch & Fisch" matches both
        self.assertTrue(matches_category_filter(herta_summary, "Fleisch & Fisch"))

        # Slug extraction and product URL generation
        self.assertEqual(dry_summary["slug"], "oryza-milch-reis")
        self.assertEqual(
            dry_summary["product_url"],
            "https://www.flaschenpost.de/p/oryza-milch-reis",
        )
        prod_with_explicit_slug = {
            "name": {"de-DE": "K-Classic Heidelbeeren"},
            "slug": {"de-DE": "k-classic-heidelbeeren-750g"},
            "masterVariant": {"sku": "32672", "price": {"value": {"centAmount": 489}}},
        }
        summary_explicit = extract_product_summary(prod_with_explicit_slug)
        self.assertEqual(summary_explicit["slug"], "k-classic-heidelbeeren-750g")
        self.assertEqual(
            summary_explicit["product_url"],
            "https://www.flaschenpost.de/p/k-classic-heidelbeeren-750g",
        )
        self.assertTrue(matches_category_filter(meat_summary, "Fleisch & Fisch"))

    def test_limitless_subcategories_hierarchy_and_filtering(self) -> None:
        """Verify recursive handling of category trees with 3, 4, or more limitless subcategory layers."""
        async def _run() -> None:
            # 4-layer category tree
            deep_tree_raw = [
                {
                    "id": "cat-1",
                    "externalId": "100",
                    "name": {"de-DE": "Kochen & Vorrat"},
                    "slug": {"de-DE": "kochen-vorrat"},
                    "children": [
                        {
                            "id": "cat-2",
                            "externalId": "200",
                            "name": {"de-DE": "Reis & Getreide"},
                            "slug": {"de-DE": "reis-getreide"},
                            "children": [
                                {
                                    "id": "cat-3",
                                    "externalId": "300",
                                    "name": {"de-DE": "Loser Reis"},
                                    "slug": {"de-DE": "loser-reis"},
                                    "children": [
                                        {
                                            "id": "cat-4",
                                            "externalId": "400",
                                            "name": {"de-DE": "Basmati Reis"},
                                            "slug": {"de-DE": "basmati-reis"},
                                            "children": [],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]

            client = FlaschenpostApiClient(email="test@example.com", password="secret")
            client._warehouse_id = 1
            client._request = lambda method, url, **kw: asyncio.sleep(0, result=deep_tree_raw)  # type: ignore[assignment]

            # 1. async_get_categories preserves all 4 layers
            tree = await client.async_get_categories()
            self.assertEqual(len(tree), 1)
            layer1 = tree[0]
            self.assertEqual(layer1["name"], "Kochen & Vorrat")
            layer2 = layer1["subcategories"][0]
            self.assertEqual(layer2["name"], "Reis & Getreide")
            layer3 = layer2["subcategories"][0]
            self.assertEqual(layer3["name"], "Loser Reis")
            layer4 = layer3["subcategories"][0]
            self.assertEqual(layer4["name"], "Basmati Reis")
            self.assertEqual(layer4["external_id"], "400")

            # 2. async_get_category_options generates dropdown options for all 4 layers
            mgr = FlaschenpostShoppingListManager(client=client)
            options = await mgr.async_get_category_options()
            vals = [o["value"] for o in options]
            labels = [o["label"] for o in options]

            self.assertIn("Kochen & Vorrat", vals)
            self.assertIn("Kochen & Vorrat (All)", labels)

            self.assertIn("Kochen & Vorrat::Reis & Getreide", vals)
            self.assertIn("Kochen & Vorrat -> Reis & Getreide (All)", labels)

            self.assertIn("Kochen & Vorrat::Reis & Getreide::Loser Reis", vals)
            self.assertIn("Kochen & Vorrat -> Reis & Getreide -> Loser Reis (All)", labels)

            self.assertIn("Kochen & Vorrat::Reis & Getreide::Loser Reis::Basmati Reis", vals)
            self.assertIn("Kochen & Vorrat -> Reis & Getreide -> Loser Reis -> Basmati Reis", labels)

            # 3. _resolve_matching_subcategory_ids matches at any level and collects subcategory IDs
            # Match layer 4 directly
            sub_ids_l4 = await client._resolve_matching_subcategory_ids(
                "Kochen & Vorrat -> Reis & Getreide -> Loser Reis -> Basmati Reis", 1
            )
            self.assertEqual(sub_ids_l4, ["400"])

            # Match layer 3 with 3 segments
            sub_ids_l3 = await client._resolve_matching_subcategory_ids(
                "Kochen & Vorrat::Reis & Getreide::Loser Reis", 1
            )
            self.assertEqual(set(sub_ids_l3), {"300", "400"})

            # Match layer 2 with 2 segments
            sub_ids_l2 = await client._resolve_matching_subcategory_ids(
                "Kochen & Vorrat -> Reis & Getreide", 1
            )
            self.assertEqual(set(sub_ids_l2), {"200", "300", "400"})

            # Match root layer 1
            sub_ids_l1 = await client._resolve_matching_subcategory_ids("Kochen & Vorrat", 1)
            self.assertEqual(set(sub_ids_l1), {"100", "200", "300", "400"})

            # Match partial path skipping root (e.g. "Loser Reis -> Basmati Reis")
            sub_ids_subpath = await client._resolve_matching_subcategory_ids(
                "Loser Reis -> Basmati Reis", 1
            )
            self.assertEqual(sub_ids_subpath, ["400"])

            # 4. matches_category_filter with 4 layers
            prod_4layer = {
                "categories": [
                    "Kochen & Vorrat",
                    "Reis & Getreide",
                    "Loser Reis",
                    "Basmati Reis",
                ],
                "category_slugs": [
                    "kochen-vorrat",
                    "reis-getreide",
                    "loser-reis",
                    "basmati-reis",
                ],
            }
            self.assertTrue(
                matches_category_filter(
                    prod_4layer,
                    "Kochen & Vorrat -> Reis & Getreide -> Loser Reis -> Basmati Reis",
                )
            )
            self.assertTrue(
                matches_category_filter(
                    prod_4layer,
                    "Reis & Getreide::Basmati Reis",
                )
            )
            self.assertTrue(matches_category_filter(prod_4layer, "Basmati Reis"))
            self.assertFalse(matches_category_filter(prod_4layer, "Jasmin Reis"))
            self.assertFalse(
                matches_category_filter(
                    prod_4layer,
                    "Kochen & Vorrat -> Nudeln -> Basmati Reis",
                )
            )

        asyncio.run(_run())

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
            "500g Reis & Getreide::Oryza Milch Reis #10495",
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

    def test_place_order_payment_resolution_without_explicit_method(self) -> None:
        """Verify calling place_order without explicit payment_method queries config and saved methods."""
        async def _run() -> None:
            # 1. Config entry options has CONF_DEFAULT_PAYMENT and CONF_STORED_PAYMENT_ID
            class _FakeEntry1:
                options = {
                    CONF_DEFAULT_PAYMENT: PAYMENT_PAYPAL,
                    CONF_STORED_PAYMENT_ID: "paypal-user@example.com",
                    CONF_IBAN_LAST4: "",
                }
                data = {}

            class _FakeCoord1:
                config_entry = _FakeEntry1()
                client = None

            m, s, i = await async_resolve_payment_parameters(_FakeCoord1())
            self.assertEqual(m, PAYMENT_PAYPAL)
            self.assertEqual(s, "paypal-user@example.com")

            # 2. Config entry data has CONF_DEFAULT_PAYMENT and CONF_STORED_PAYMENT_ID (empty options)
            class _FakeEntry2:
                options = {}
                data = {
                    CONF_DEFAULT_PAYMENT: PAYMENT_CREDIT_CARD,
                    CONF_STORED_PAYMENT_ID: "card-stored-456",
                }

            class _FakeCoord2:
                config_entry = _FakeEntry2()
                client = None

            m, s, i = await async_resolve_payment_parameters(_FakeCoord2())
            self.assertEqual(m, PAYMENT_CREDIT_CARD)
            self.assertEqual(s, "card-stored-456")

            # 3. Explicit parameter overrides config entry
            m, s, i = await async_resolve_payment_parameters(
                _FakeCoord2(), payment_method=PAYMENT_SEPA, iban_last4="9876"
            )
            self.assertEqual(m, PAYMENT_SEPA)
            self.assertEqual(i, "9876")

            # 4. Neither config nor explicit, but client has saved payment methods -> dynamically queries client
            class _FakeClientWithSaved:
                async def async_get_saved_payment_methods(self):
                    return [
                        {
                            "id": "credit_card:sp-primary-card",
                            "payment_method": PAYMENT_CREDIT_CARD,
                            "stored_payment_id": "sp-primary-card",
                            "brand": "mastercard",
                        }
                    ]

            class _FakeEntry3:
                options = {}
                data = {}

            class _FakeCoord3:
                config_entry = _FakeEntry3()
                client = _FakeClientWithSaved()

            m, s, i = await async_resolve_payment_parameters(_FakeCoord3())
            self.assertEqual(m, PAYMENT_CREDIT_CARD)
            self.assertEqual(s, "sp-primary-card")

            # 5. Neither config, explicit, nor saved methods on client -> defaults to credit_card, NEVER sepa
            class _FakeClientNoSaved:
                async def async_get_saved_payment_methods(self):
                    return []

            class _FakeCoord4:
                config_entry = _FakeEntry3()
                client = _FakeClientNoSaved()

            m, s, i = await async_resolve_payment_parameters(_FakeCoord4())
            self.assertEqual(m, PAYMENT_CREDIT_CARD)
            self.assertNotEqual(m, PAYMENT_SEPA)

            # 6. Verify FlaschenpostApiClient.async_place_order default without payment_method uses client attributes
            client = FlaschenpostApiClient(
                email="test@example.com",
                password="secret",
                default_payment_method=PAYMENT_CREDIT_CARD,
                stored_payment_id="sp-auto-card",
            )
            client._cart_id = "cart-uuid"
            recalc_cart = {
                "id": "cart-uuid",
                "lineItems": [{"id": "li-1", "quantity": 1}],
                "totalPrice": {"centAmount": 3000},
                "shippingAddress": {"key": "k1", "custom": {"fields": {"AddressReference": "ref-1"}}},
                "shippingCustomFields": {"fields": {"SelectedDeliveryType": "DIRECT"}},
            }
            adyen_payments_called = []

            async def _fake_req(method, url, params=None, json_body=None, **kwargs):
                if "validatestock" in url:
                    return {}
                if "adyen/init" in url:
                    return {
                        "paymentId": "pay-adyen",
                        "adyenSessionResponse": {"id": "sess-adyen", "sessionData": "sess-data"},
                    }
                if "checkout/init" in url or "checkout/complete" in url:
                    return {"order": {"id": "ord-auto-99", "orderNumber": "FP-AUTO-99"}}
                return recalc_cart

            client._request = _fake_req  # type: ignore[assignment]
            client.async_apply_cart_actions = lambda acts: asyncio.sleep(0, result=recalc_cart)  # type: ignore[assignment]

            class _FakeAdyenResp:
                def __init__(self, data):
                    self._data = data
                async def json(self):
                    return self._data
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass

            class _FakeAdyenSession:
                def post(self, url, json=None, **kwargs):
                    if "sessions" in url and "setup" in url:
                        return _FakeAdyenResp({"storedPaymentMethods": [{"id": "sp-auto-card", "type": "scheme"}]})
                    if "sessions" in url and "payments" in url:
                        adyen_payments_called.append(json)
                        return _FakeAdyenResp({"resultCode": "Authorised"})
                    return _FakeAdyenResp({})

            client._session = _FakeAdyenSession()  # type: ignore[assignment]

            # Place order WITHOUT passing payment_method
            order = await client.async_place_order()
            self.assertEqual(order["orderNumber"], "FP-AUTO-99")
            self.assertEqual(len(adyen_payments_called), 1)
            self.assertEqual(
                adyen_payments_called[0]["paymentMethod"]["storedPaymentMethodId"],
                "sp-auto-card",
            )

        asyncio.run(_run())

    def test_place_order_flow(self) -> None:
        async def _run() -> None:
            self.assertEqual(SERVICE_PLACE_ORDER, "place_order")
            self.assertEqual(SERVICE_GET_STORED_PAYMENT_ID, "get_stored_payment_id")
            self.assertEqual(SERVICE_GET_PAYMENT_METHODS, "get_payment_methods")

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
                self.last_update_success_time = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)
                self.next_update_time = datetime(2026, 11, 4, 12, 5, 0, tzinfo=UTC)
                self.update_interval = timedelta(minutes=5)

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
            self.assertEqual(len(registered_cmds), 21)

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
            self.assertIn("last_updated", conn.results[9])
            self.assertIn("next_update", conn.results[9])
            self.assertEqual(conn.results[9]["update_interval_seconds"], 300)

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

            # 12. ws_buy_cart & ws_place_order: confirmed
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

            # 12b. ws_place_order
            await ws_place_order(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 120,
                    "type": "flaschenpost/place_order",
                    "confirm": True,
                },
            )
            self.assertIn(120, conn.results)
            self.assertEqual(conn.results[120]["order_id"], "ord-mock-123")

            # 12c. ws_get_stored_payment_id
            await ws_get_stored_payment_id(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 121,
                    "type": "flaschenpost/get_stored_payment_id",
                },
            )
            self.assertIn(121, conn.results)
            self.assertIn("stored_payment_id", conn.results[121])

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

            # 14. ws_import_cart_to_list
            await ws_import_cart_to_list(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 14,
                    "type": "flaschenpost/import_cart_to_list",
                    "name": "Cart Import",
                },
            )
            self.assertIn(14, conn.results)
            self.assertTrue(conn.results[14]["success"])
            self.assertEqual(conn.results[14]["name"], "Cart Import")
            self.assertEqual(conn.results[14]["imported_count"], 1)
            self.assertEqual(conn.results[14]["items"][0]["article_id"], 32672)

            # 15. ws_set_list_config
            await ws_set_list_config(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 15,
                    "type": "flaschenpost/set_list_config",
                    "name": "Cart Import",
                    "random_enabled": True,
                    "random_count": 2,
                },
            )
            self.assertIn(15, conn.results)
            self.assertTrue(conn.results[15]["config"]["random_enabled"])
            self.assertEqual(conn.results[15]["config"]["random_count"], 2)

            # 16. ws_reset_list_weights
            await ws_reset_list_weights(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 16,
                    "type": "flaschenpost/reset_list_weights",
                    "name": "Cart Import",
                },
            )
            self.assertIn(16, conn.results)
            self.assertTrue(conn.results[16]["success"])

            # 17. ws_refresh
            await ws_refresh(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 17,
                    "type": "flaschenpost/refresh",
                },
            )
            self.assertIn(17, conn.results)
            self.assertTrue(conn.results[17]["success"])
            self.assertIn("last_updated", conn.results[17])
            self.assertIn("next_update", conn.results[17])
            self.assertEqual(conn.results[17]["update_interval_seconds"], 300)

            # 18. ws_add_coupon
            await ws_add_coupon(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 18,
                    "type": "flaschenpost/add_coupon",
                    "code": "FLASCHE10",
                    "description": "10€ Rabatt",
                },
            )
            self.assertIn(18, conn.results)
            self.assertEqual(conn.results[18]["coupon"]["code"], "FLASCHE10")

            # 19. ws_get_coupons
            await ws_get_coupons(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 19,
                    "type": "flaschenpost/get_coupons",
                },
            )
            self.assertIn(19, conn.results)
            self.assertTrue(any(c["code"] == "FLASCHE10" for c in conn.results[19]["coupons"]))

            # 20. ws_delete_coupon
            await ws_delete_coupon(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {
                    "id": 20,
                    "type": "flaschenpost/delete_coupon",
                    "code": "FLASCHE10",
                },
            )
            self.assertIn(20, conn.results)
            self.assertTrue(conn.results[20]["deleted"])

            # 21. Verify frontend panel JS asset exists and contains web component
            panel_js_file = _PKG_DIR / "frontend" / "flaschenpost-panel.js"
            self.assertTrue(panel_js_file.exists())
            js_content = panel_js_file.read_text(encoding="utf-8")
            self.assertIn("flaschenpost-panel", js_content)
            self.assertIn("flaschenpost-card", js_content)
            self.assertIn("flaschenpost-view", js_content)

        asyncio.run(_run())

    def test_mengenrabatte_and_optimal_pack_plan(self) -> None:
        """Verify Mengenrabatte (volume discounts): Item B (119€, 60€ off at 3) beats Item A (99€) when needing 2 items."""
        # 1. Test tier extraction from Commercetools price.tiers
        ct_variant = {
            "sku": "1002",
            "price": {
                "value": {"centAmount": 11900},
                "tiers": [
                    {
                        "minimumQuantity": 3,
                        "value": {"centAmount": 5900},
                    }
                ],
            },
        }
        tiers_ct = extract_price_tiers(ct_variant, 119.0, {}, ct_variant["price"])
        self.assertEqual(len(tiers_ct), 1)
        self.assertEqual(tiers_ct[0]["min_quantity"], 3)
        self.assertEqual(tiers_ct[0]["unit_price_eur"], 59.0)
        self.assertEqual(tiers_ct[0]["discount_eur"], 60.0)

        # 2. Test tier extraction from attributes (e.g. Mengenrabatt / Staffelpreise with discount off)
        attr_variant = {
            "sku": "1003",
            "price": {"value": {"centAmount": 11900}},
            "attributes": [
                {
                    "name": "Mengenrabatt",
                    "value": [
                        {"min_quantity": 3, "discount": 60.0}
                    ]
                }
            ],
        }
        attrs = {"Mengenrabatt": [{"min_quantity": 3, "discount": 60.0}]}
        tiers_attr = extract_price_tiers(attr_variant, 119.0, attrs, attr_variant["price"])
        self.assertEqual(len(tiers_attr), 1)
        self.assertEqual(tiers_attr[0]["min_quantity"], 3)
        self.assertEqual(tiers_attr[0]["unit_price_eur"], 59.0)

        # 3. Test compute_optimal_pack_plan
        item_a = {"article_id": 1001, "name": "Item A", "price_eur": 99.0, "price_tiers": []}
        item_b = {
            "article_id": 1002,
            "name": "Item B",
            "price_eur": 119.0,
            "price_tiers": [{"min_quantity": 3, "unit_price_eur": 59.0, "discount_eur": 60.0}],
        }

        # Need 2 items:
        # Item A: 2x 99€ = 198€
        # Item B without discount: 2x 119€ = 238€
        # Item B hitting Mengenrabatt: 3x 59€ = 177€
        plan_a = compute_optimal_pack_plan(item_a, 2)
        plan_b = compute_optimal_pack_plan(item_b, 2)

        self.assertEqual(plan_a, (2, 99.0, 198.0, False))
        self.assertEqual(plan_b, (3, 59.0, 177.0, True))

        # 4. Test estimate_candidate_pack_plan
        spec_2x = parse_shopping_item_spec("2x Item")
        cand_plan_a = estimate_candidate_pack_plan(spec_2x, item_a)
        cand_plan_b = estimate_candidate_pack_plan(spec_2x, item_b)

        self.assertEqual(cand_plan_a["packs"], 2)
        self.assertEqual(cand_plan_a["line_total_eur"], 198.0)
        self.assertFalse(cand_plan_a["tier_applied"])

        self.assertEqual(cand_plan_b["packs"], 3)
        self.assertEqual(cand_plan_b["line_total_eur"], 177.0)
        self.assertTrue(cand_plan_b["tier_applied"])
        self.assertIn("Mengenrabatt", cand_plan_b["base_metric"])

        # 5. Full resolution test through async_resolve_item_for_cart
        async def _run() -> None:
            client = FlaschenpostApiClient(email="test@example.com", password="secret")
            client._warehouse_id = 10

            async def _fake_search(q, **kwargs):
                return [item_a, item_b]

            client.async_search_products = _fake_search

            # Resolve 2 items: Item B (177€ for 3) must beat Item A (198€ for 2)
            winner = await client.async_resolve_item_for_cart("Item", target_amount_base=2.0, sort_by="price")
            self.assertIsNotNone(winner)
            self.assertEqual(winner["article_id"], 1002)
            self.assertEqual(winner["quantity"], 3)
            self.assertEqual(winner["line_total_eur"], 177.0)
            self.assertEqual(winner["unit_price_eur"], 59.0)
            self.assertTrue(winner["tier_applied"])

            # Also check preview_search in manager
            manager = FlaschenpostShoppingListManager(client=client)
            preview = await manager.async_preview_search("2x Item")
            self.assertIsNotNone(preview["winner"])
            self.assertEqual(preview["winner"]["article_id"], 1002)
            self.assertEqual(preview["winner"]["quantity"], 3)
            self.assertEqual(preview["winner"]["line_total_eur"], 177.0)

            # Candidates list: Item B must be first, Item A second
            self.assertEqual(preview["candidates"][0]["article_id"], 1002)
            self.assertEqual(preview["candidates"][0]["line_total_eur"], 177.0)
            self.assertEqual(preview["candidates"][1]["article_id"], 1001)
            self.assertEqual(preview["candidates"][1]["line_total_eur"], 198.0)

        asyncio.run(_run())

    def test_preview_search_category_filter_reflected(self) -> None:
        """Verify category filter is strictly enforced and reflected in preview candidates and pinned summary."""
        async def _run() -> None:
            fake_client = _FakeApiClient()
            mgr = FlaschenpostShoppingListManager(client=fake_client)  # type: ignore[arg-type]

            # Query without category: cand_29010 (Obst- & Gemüsekonserven) is cheaper and wins
            preview_all = await mgr.async_preview_search("Heidelbeeren")
            self.assertEqual(preview_all["winner"]["article_id"], 29010)
            self.assertEqual(len(preview_all["candidates"]), 2)

            # Query with category Tiefkühl: only cand_32672 (Tiefkühl) matches
            preview_cat = await mgr.async_preview_search("Heidelbeeren", category="Tiefkühl")
            self.assertEqual(preview_cat["winner"]["article_id"], 32672)
            self.assertEqual(len(preview_cat["candidates"]), 1)
            self.assertEqual(preview_cat["candidates"][0]["article_id"], 32672)
            self.assertEqual(preview_cat["lazy_summary"], "Tiefkühl::Heidelbeeren")
            self.assertIn("Category: *Tiefkühl > Obst*", preview_cat["markdown"])
            self.assertIn("Tiefkühl::", preview_cat["candidates"][0]["pinned_summary"])

        asyncio.run(_run())

    def test_cart_import_and_weighted_randomizer(self) -> None:
        """Verify importing cart line items by SKU and weighted random picking per list."""
        async def _run() -> None:
            fake_client = _FakeApiClient()
            mgr = FlaschenpostShoppingListManager(client=fake_client)  # type: ignore[arg-type]

            # 1. Import cart with items into a new list
            items = await mgr.async_import_cart_to_new_list("Warenkorb Import")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].article_id, 32672)
            self.assertIn("#32672", items[0].summary)
            self.assertEqual(items[0].weight, DEFAULT_ITEM_WEIGHT)
            self.assertIn("Warenkorb Import", mgr.list_names)

            # 2. Reject empty cart
            fake_client_empty = _FakeApiClient()
            fake_client_empty.async_get_cart = lambda: asyncio.sleep(0, result={"lineItems": []})  # type: ignore[assignment]
            mgr_empty = FlaschenpostShoppingListManager(client=fake_client_empty)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                await mgr_empty.async_import_cart_to_new_list("Empty List")

            # 3. Setup list for randomizer testing
            # Add 4 items: A, B, C, D
            await mgr.async_save_named_list(
                "Snacks",
                [
                    "K-Classic Heidelbeeren #32672",
                    "Alnatura Bio Wildheidelbeeren #18089",
                    "Oryza Milch Reis #10495",
                    "K-Classic Naturjoghurt 1,5% #28435",
                ],
                replace=True,
            )
            cfg = await mgr.async_set_list_config("Snacks", random_enabled=True, random_count=2)
            self.assertTrue(cfg.random_enabled)
            self.assertEqual(cfg.random_count, 2)

            # Check all initial weights are 1.0
            initial_items = mgr.get_list_items("Snacks")
            self.assertEqual(len(initial_items), 4)
            for it in initial_items:
                self.assertEqual(it.weight, 1.0)

            # 4. Dry-run preview should pick 2 items, but NOT mutate weights
            preview = await mgr.async_preview_lists(["Snacks"])
            self.assertEqual(len(preview["resolved_items"]), 2)
            for it in mgr.get_list_items("Snacks"):
                self.assertEqual(it.weight, 1.0)

            # 5. Real cart add (dry_run=False) should mutate weights
            res = await mgr.async_add_lists_to_cart(["Snacks"], dry_run=False)
            self.assertEqual(len(res["resolved_items"]), 2)
            picked_aids = {r["article_id"] for r in res["resolved_items"]}
            self.assertEqual(len(picked_aids), 2)

            after_run_1 = mgr.get_list_items("Snacks")
            for it in after_run_1:
                if it.article_id in picked_aids:
                    self.assertEqual(it.weight, 1.0, f"Picked item {it.article_id} should reset to weight 1.0")
                else:
                    self.assertEqual(it.weight, 2.0, f"Unpicked item {it.article_id} should increase weight to 2.0")

            # 6. Run successive syncs and verify all items eventually get picked due to increasing weights
            all_picked_aids: set[int] = set(picked_aids)
            for _ in range(15):
                res_i = await mgr.async_add_lists_to_cart(["Snacks"], dry_run=False)
                for r in res_i["resolved_items"]:
                    all_picked_aids.add(r["article_id"])

            self.assertEqual(all_picked_aids, {32672, 18089, 10495, 28435}, "All items must eventually be picked")

            # 7. Test reset weights
            await mgr.async_reset_list_weights("Snacks")
            for it in mgr.get_list_items("Snacks"):
                self.assertEqual(it.weight, 1.0)

        asyncio.run(_run())


    def test_sqlite_storage_and_legacy_todo_migration(self) -> None:
        """Verify SQLite persistence engine, CRUD operations, and one-time legacy Store migration."""
        import sqlite3
        import tempfile

        async def _run() -> None:
            fake_client = _FakeApiClient()
            with tempfile.TemporaryDirectory() as tmp_dir:
                db_path = Path(tmp_dir) / "flaschenpost.db"

                # 1. Mock legacy store with v2 shopping lists format
                class _MockLegacyStore:
                    def __init__(self, data: dict[str, Any]) -> None:
                        self._data = data

                    async def async_load(self) -> dict[str, Any]:
                        return self._data

                    async def async_save(self, data: dict[str, Any]) -> None:
                        self._data = data

                legacy_data = {
                    "lists": {
                        "Weekly Grocery": [
                            {
                                "uid": "item-1",
                                "summary": "1kg Naturjoghurt #28435",
                                "query": "Naturjoghurt",
                                "category": None,
                                "unit_type": "weight_g",
                                "target_amount_base": 1000.0,
                                "quantity": 1,
                                "article_id": 28435,
                                "sort_by": None,
                                "negative_keywords": ["zucker"],
                                "completed": False,
                                "weight": 2.5,
                            }
                        ],
                        "Drinks": [
                            {
                                "uid": "item-2",
                                "summary": "Pepsi Zero Zucker #1838",
                                "query": "Pepsi Zero",
                                "category": "Getränke",
                                "unit_type": "unit",
                                "target_amount_base": 1.0,
                                "quantity": 2,
                                "article_id": 1838,
                                "sort_by": None,
                                "negative_keywords": [],
                                "completed": True,
                                "weight": 1.0,
                            }
                        ],
                    },
                    "list_configs": {
                        "Weekly Grocery": {
                            "random_enabled": True,
                            "random_count": 3,
                        }
                    },
                }
                legacy_store = _MockLegacyStore(legacy_data)

                # 2. Initialize FlaschenpostShoppingListManager with SQLite storage and legacy store
                storage = FlaschenpostSqliteStorage(db_path=db_path)
                mgr = FlaschenpostShoppingListManager(
                    client=fake_client,  # type: ignore[arg-type]
                    storage=storage,
                    store=legacy_store,
                )

                await mgr.async_load()

                # Verify migrated lists and configurations
                self.assertIn("Weekly Grocery", mgr.list_names)
                self.assertIn("Drinks", mgr.list_names)
                self.assertIn(DEFAULT_SHOPPING_LIST_NAME, mgr.list_names)

                wg_items = mgr.get_list_items("Weekly Grocery")
                self.assertEqual(len(wg_items), 1)
                self.assertEqual(wg_items[0].summary, "1kg Naturjoghurt #28435")
                self.assertEqual(wg_items[0].article_id, 28435)
                self.assertEqual(wg_items[0].weight, 2.5)
                self.assertEqual(wg_items[0].negative_keywords, ["zucker"])

                drinks_items = mgr.get_list_items("Drinks")
                self.assertEqual(len(drinks_items), 1)
                self.assertEqual(drinks_items[0].completed, True)

                wg_cfg = mgr.get_list_config("Weekly Grocery")
                self.assertTrue(wg_cfg.random_enabled)
                self.assertEqual(wg_cfg.random_count, 3)

                # Verify metadata table in SQLite
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM metadata WHERE key = 'todo_migrated';")
                row = cursor.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "true")
                conn.close()

                # Verify migration is NOT re-run if store data changes afterwards
                legacy_store._data = {"lists": {"Tampered List": []}}
                storage.close()

                # 3. Reload from SQLite with a new manager instance and verify persistence
                storage_reloaded = FlaschenpostSqliteStorage(db_path=db_path)
                mgr2 = FlaschenpostShoppingListManager(
                    client=fake_client,  # type: ignore[arg-type]
                    storage=storage_reloaded,
                    store=legacy_store,
                )
                await mgr2.async_load()
                self.assertNotIn("Tampered List", mgr2.list_names)
                self.assertIn("Weekly Grocery", mgr2.list_names)
                self.assertEqual(len(mgr2.get_list_items("Weekly Grocery")), 1)

                # 4. Test CRUD operations via manager persisting to SQLite
                # Add item
                new_item = await mgr2.async_add_item(
                    summary="500g Heidelbeeren !bio",
                    list_name="Weekly Grocery",
                )
                self.assertEqual(len(mgr2.get_list_items("Weekly Grocery")), 2)

                # Update item
                await mgr2.async_update_item(
                    new_item.uid,
                    summary="500g Heidelbeeren [€/kg]",
                    completed=True,
                    list_name="Weekly Grocery",
                )
                updated_items = mgr2.get_list_items("Weekly Grocery")
                it_updated = next(x for x in updated_items if x.uid == new_item.uid)
                self.assertTrue(it_updated.completed)
                self.assertEqual(it_updated.sort_by, SORT_PRICE_PER_KG)

                # Delete list
                await mgr2.async_delete_named_list("Drinks")
                self.assertNotIn("Drinks", mgr2.list_names)

                # 5. Reload again to verify changes are stored in SQLite
                storage_reloaded.close()
                storage3 = FlaschenpostSqliteStorage(db_path=db_path)
                mgr3 = FlaschenpostShoppingListManager(
                    client=fake_client,  # type: ignore[arg-type]
                    storage=storage3,
                )
                await mgr3.async_load()
                self.assertNotIn("Drinks", mgr3.list_names)
                self.assertEqual(len(mgr3.get_list_items("Weekly Grocery")), 2)
                storage3.close()

        asyncio.run(_run())

    def test_update_countdown_and_freshness_sensors(self) -> None:
        """Verify coordinator timestamps, adaptive delivery intervals, and freshness sensors."""
        async def _run() -> None:
            fake_client = _FakeApiClient()
            mgr = FlaschenpostShoppingListManager(client=fake_client)  # type: ignore[arg-type]
            mock_entry = types.SimpleNamespace(entry_id="test_entry", title="Test Account")
            mock_hass = types.SimpleNamespace(data={})

            coord = FlaschenpostCoordinator(
                hass=mock_hass,  # type: ignore[arg-type]
                entry=mock_entry,  # type: ignore[arg-type]
                client=fake_client,  # type: ignore[arg-type]
                shopping_list=mgr,
            )

            # 1. Initially timestamps are None
            self.assertIsNone(coord.last_update_success_time)
            self.assertIsNone(coord.next_update_time)

            # 2. Simulate successful update
            now_utc = datetime(2026, 11, 4, 14, 0, 0, tzinfo=UTC)
            coord.last_update_success_time = now_utc
            self.assertEqual(coord.update_interval, timedelta(minutes=5))
            self.assertEqual(coord.next_update_time, now_utc + timedelta(minutes=5))

            # 3. Simulate active delivery snapshot (adaptive polling speedup to 60s)
            coord.data = FlaschenpostSnapshot(
                active_orders=[{"id": "order-123"}],
                cart={"totalPrice": {"centAmount": 4550}},
            )
            coord.update_interval = timedelta(seconds=60)
            self.assertEqual(coord.next_update_time, now_utc + timedelta(seconds=60))

            # 4. Next update sensor
            next_sensor = FlaschenpostNextUpdateSensor(coord)
            self.assertEqual(next_sensor.native_value, now_utc + timedelta(seconds=60))
            attrs = next_sensor.extra_state_attributes
            self.assertEqual(attrs["last_updated"], now_utc.isoformat())
            self.assertEqual(attrs["update_interval_seconds"], 60)
            self.assertEqual(attrs["update_interval_human"], "1m")
            self.assertTrue(attrs["active_delivery_mode"])
            self.assertEqual(attrs["last_update_status"], "success")

            # 5. Last update sensor
            last_sensor = FlaschenpostLastUpdateSensor(coord)
            self.assertEqual(last_sensor.native_value, now_utc)
            last_attrs = last_sensor.extra_state_attributes
            self.assertEqual(last_attrs["next_update"], (now_utc + timedelta(seconds=60)).isoformat())
            self.assertEqual(last_attrs["update_interval_seconds"], 60)
            self.assertTrue(last_attrs["active_delivery_mode"])

            # 6. Cart total sensor includes freshness attributes
            cart_sensor = FlaschenpostCartTotalSensor(coord)
            cart_attrs = cart_sensor.extra_state_attributes
            self.assertEqual(cart_attrs["last_updated"], now_utc.isoformat())
            self.assertEqual(cart_attrs["next_update"], (now_utc + timedelta(seconds=60)).isoformat())

            # 7. Refresh button
            refreshed = False
            async def _fake_refresh() -> None:
                nonlocal refreshed
                refreshed = True
            coord.async_request_refresh = _fake_refresh  # type: ignore[method-assign]
            btn = FlaschenpostRefreshButton(coord)
            await btn.async_press()
            self.assertTrue(refreshed)

        asyncio.run(_run())

    def test_empty_cart_total_and_fee_suppression(self) -> None:
        """Verify cart total sensor and ws_get_cart report 0.00 EUR when cart has no line items."""
        async def _run() -> None:
            fake_client = _FakeApiClient()
            mgr = FlaschenpostShoppingListManager(client=fake_client)  # type: ignore[arg-type]
            mock_entry = types.SimpleNamespace(entry_id="test_entry", title="Test Account")
            mock_hass = types.SimpleNamespace(data={})

            coord = FlaschenpostCoordinator(
                hass=mock_hass,  # type: ignore[arg-type]
                entry=mock_entry,  # type: ignore[arg-type]
                client=fake_client,  # type: ignore[arg-type]
                shopping_list=mgr,
            )

            # 1. Empty cart with staged Commercetools delivery fee (3.90 EUR) and 0 line items
            coord.data = FlaschenpostSnapshot(
                cart={
                    "id": "cart-empty-1",
                    "totalPrice": {"centAmount": 390},
                    "shippingInfo": {"price": {"centAmount": 390}},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 0},
                            "TotalDeposit": {"centAmount": 0},
                            "TotalDelivery": {"centAmount": 390},
                            "MinimumOrderValue": 2500,
                        }
                    },
                    "lineItems": [],
                    "totalLineItemQuantity": 0,
                }
            )

            sensor = FlaschenpostCartTotalSensor(coord)
            self.assertEqual(sensor.native_value, 0.0)
            attrs = sensor.extra_state_attributes
            self.assertEqual(attrs["item_count"], 0)
            self.assertEqual(attrs["goods_eur"], 0.0)
            self.assertEqual(attrs["delivery_fee_eur"], 0.0)
            self.assertEqual(attrs["deposit_eur"], 0.0)
            self.assertEqual(attrs["items"], [])

            # 2. Non-empty cart
            coord.data = FlaschenpostSnapshot(
                cart={
                    "id": "cart-filled-1",
                    "totalPrice": {"centAmount": 2850},
                    "shippingInfo": {"price": {"centAmount": 0}},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 2850},
                            "TotalDeposit": {"centAmount": 0},
                            "TotalDelivery": {"centAmount": 0},
                            "MinimumOrderValue": 2500,
                        }
                    },
                    "lineItems": [
                        {
                            "id": "li-1",
                            "variant": {"sku": "12345"},
                            "name": {"de-DE": "Apfelsaft"},
                            "quantity": 2,
                            "totalPrice": {"centAmount": 2850},
                        }
                    ],
                    "totalLineItemQuantity": 2,
                }
            )
            self.assertEqual(sensor.native_value, 28.5)
            filled_attrs = sensor.extra_state_attributes
            self.assertEqual(filled_attrs["item_count"], 2)
            self.assertEqual(filled_attrs["goods_eur"], 28.5)
            self.assertEqual(filled_attrs["delivery_fee_eur"], 0.0)

            # 3. ws_get_cart with empty cart
            class _EmptyCartClient(_FakeApiClient):
                async def async_get_cart(self) -> dict[str, Any]:
                    return {
                        "id": "cart-empty-ws",
                        "totalPrice": {"centAmount": 390},
                        "shippingInfo": {"price": {"centAmount": 390}},
                        "custom": {"fields": {"MinimumOrderValue": 2500}},
                        "lineItems": [],
                    }

            empty_client = _EmptyCartClient()
            empty_coord = FlaschenpostCoordinator(
                hass=mock_hass,  # type: ignore[arg-type]
                entry=mock_entry,  # type: ignore[arg-type]
                client=empty_client,  # type: ignore[arg-type]
                shopping_list=FlaschenpostShoppingListManager(client=empty_client),  # type: ignore[arg-type]
            )
            mock_hass.data["flaschenpost"] = {"test_entry": empty_coord}

            class _MockConn:
                def __init__(self) -> None:
                    self.results: dict[int, Any] = {}
                    self.errors: dict[int, tuple[str, str]] = {}

                def send_result(self, msg_id: int, result: Any) -> None:
                    self.results[msg_id] = result

                def send_error(self, msg_id: int, code: str, message: str) -> None:
                    self.errors[msg_id] = (code, message)

            conn = _MockConn()
            await ws_get_cart(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {"id": 100, "type": "flaschenpost/get_cart", "config_entry_id": "test_entry"},
            )
            self.assertIn(100, conn.results)
            res = conn.results[100]
            self.assertEqual(res["total_eur"], 0.0)
            self.assertEqual(res["shipping_fee_eur"], 0.0)
            self.assertFalse(res["min_order_reached"])
            self.assertEqual(res["remaining_to_min_eur"], 25.0)
            self.assertEqual(res["items"], [])

            # 4. ws_get_cart with loaded cart containing Commercetools CentPrecisionMoney dicts
            class _LoadedCartClient(_FakeApiClient):
                async def async_get_cart(self) -> dict[str, Any]:
                    return {
                        "id": "cart-loaded-ws",
                        "totalPrice": {"centAmount": 10344, "currencyCode": "EUR", "type": "centPrecision", "fractionDigits": 2},
                        "shippingInfo": {"price": {"centAmount": 0, "currencyCode": "EUR", "type": "centPrecision", "fractionDigits": 2}},
                        "custom": {
                            "fields": {
                                "TotalGoods": {"centAmount": 9684, "currencyCode": "EUR", "type": "centPrecision", "fractionDigits": 2},
                                "MinimumOrderValue": None,
                            }
                        },
                        "lineItems": [
                            {
                                "variant": {"sku": "28435"},
                                "product": {"name": {"de": "K-Classic Naturjoghurt 1,5%"}},
                                "quantity": 5,
                                "price": {"value": {"centAmount": 89, "fractionDigits": 2}},
                                "totalPrice": {"centAmount": 445, "fractionDigits": 2},
                            }
                        ],
                    }

            loaded_client = _LoadedCartClient()
            loaded_coord = FlaschenpostCoordinator(
                hass=mock_hass,  # type: ignore[arg-type]
                entry=mock_entry,  # type: ignore[arg-type]
                client=loaded_client,  # type: ignore[arg-type]
                shopping_list=FlaschenpostShoppingListManager(client=loaded_client),  # type: ignore[arg-type]
            )
            mock_hass.data["flaschenpost"] = {"test_entry": loaded_coord}

            await ws_get_cart(
                mock_hass,  # type: ignore[arg-type]
                conn,  # type: ignore[arg-type]
                {"id": 101, "type": "flaschenpost/get_cart", "config_entry_id": "test_entry"},
            )
            self.assertIn(101, conn.results)
            l_res = conn.results[101]
            self.assertEqual(l_res["total_eur"], 103.44)
            self.assertEqual(l_res["shipping_fee_eur"], 0.0)
            self.assertEqual(l_res["min_order_value_eur"], 25.0)
            self.assertTrue(l_res["min_order_reached"])
            self.assertEqual(l_res["remaining_to_min_eur"], 0.0)
            self.assertEqual(len(l_res["items"]), 1)
            self.assertEqual(l_res["items"][0]["article_id"], "28435")
            self.assertEqual(l_res["items"][0]["name"], "K-Classic Naturjoghurt 1,5%")
            self.assertEqual(l_res["items"][0]["unit_price_eur"], 0.89)
            self.assertEqual(l_res["items"][0]["total_eur"], 4.45)

        asyncio.run(_run())


    def test_coupon_database_and_order_redemption(self) -> None:
        """Verify coupon codes are stored in SQLite DB, queried, and redeemed on next order."""
        import tempfile

        async def _run() -> None:
            fake_client = _FakeApiClient()
            with tempfile.TemporaryDirectory() as tmp_dir:
                db_path = Path(tmp_dir) / "flaschenpost.db"
                storage = FlaschenpostSqliteStorage(str(db_path))
                await storage.async_init()

                # 1. Initially no coupons
                coupons = await storage.async_get_coupons()
                self.assertEqual(coupons, [])

                # 2. Add active coupons
                c1 = await storage.async_add_coupon("FLASCHE10", "10 Euro Willkommensgutschein")
                self.assertEqual(c1["code"], "FLASCHE10")
                self.assertEqual(c1["status"], "active")
                self.assertEqual(c1["description"], "10 Euro Willkommensgutschein")

                c2 = await storage.async_add_coupon("sommer5", "5 Euro Sommeraktion")
                self.assertEqual(c2["code"], "SOMMER5")  # Uppercased

                all_c = await storage.async_get_coupons()
                self.assertEqual(len(all_c), 2)
                active_c = await storage.async_get_active_coupons()
                self.assertEqual(len(active_c), 2)

                # 3. Manager integration & auto-apply to cart
                mgr = FlaschenpostShoppingListManager(client=fake_client, storage=storage)
                applied = await mgr.async_apply_next_coupon_to_cart()
                self.assertIsNotNone(applied)
                self.assertEqual(applied["code"], "FLASCHE10")
                self.assertIn("FLASCHE10", fake_client.applied_discount_codes)

                # 4. Mark coupon used on order completion
                await storage.async_mark_coupon_used("FLASCHE10", "ord-mock-777")
                active_after = await storage.async_get_active_coupons()
                self.assertEqual(len(active_after), 1)
                self.assertEqual(active_after[0]["code"], "SOMMER5")

                used_c = await storage.async_get_coupons(status="used")
                self.assertEqual(len(used_c), 1)
                self.assertEqual(used_c[0]["code"], "FLASCHE10")
                self.assertEqual(used_c[0]["order_id"], "ord-mock-777")
                self.assertIsNotNone(used_c[0]["used_at"])

                # 5. Delete coupon
                del_res = await storage.async_delete_coupon("SOMMER5")
                self.assertTrue(del_res)
                active_final = await storage.async_get_active_coupons()
                self.assertEqual(len(active_final), 0)

        asyncio.run(_run())


    def test_spending_summary_sensors(self) -> None:
        """Verify weekly, monthly, yearly, and total spent summary sensors and SQLite order persistence."""
        import tempfile

        async def _run() -> None:
            fake_client = _FakeApiClient()
            mock_entry = types.SimpleNamespace(entry_id="test_entry", title="Test Account")
            mock_hass = types.SimpleNamespace(data={})

            with tempfile.TemporaryDirectory() as tmp_dir:
                db_path = Path(tmp_dir) / "flaschenpost.db"
                storage = FlaschenpostSqliteStorage(str(db_path))
                await storage.async_init()
                mgr = FlaschenpostShoppingListManager(client=fake_client, storage=storage)

                coord = FlaschenpostCoordinator(
                    hass=mock_hass,  # type: ignore[arg-type]
                    entry=mock_entry,  # type: ignore[arg-type]
                    client=fake_client,  # type: ignore[arg-type]
                    shopping_list=mgr,
                )

                # Reference "now": 2026-11-04T14:00:00Z (Wednesday)
                # Week start: 2026-11-02T00:00:00Z (Monday)
                # Month start: 2026-11-01T00:00:00Z (Sunday)
                # Year start: 2026-01-01T00:00:00Z

                order_this_week = {
                    "id": "ord-this-week",
                    "orderNumber": "1001",
                    "createdAt": "2026-11-03T12:00:00Z",
                    "totalPrice": {"centAmount": 4550},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 4000},
                            "TotalDeposit": {"centAmount": 250},
                            "TotalDelivery": {"centAmount": 300},
                            "OfficialStatusIconState": "delivered",
                        }
                    },
                    "orderState": "Complete",
                }
                order_earlier_this_month = {
                    "id": "ord-earlier-month",
                    "orderNumber": "1002",
                    "createdAt": "2026-11-01T15:00:00Z",
                    "totalPrice": {"centAmount": 3000},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 2500},
                            "TotalDeposit": {"centAmount": 500},
                            "TotalDelivery": {"centAmount": 0},
                            "OfficialStatusIconState": "delivered",
                        }
                    },
                    "orderState": "Complete",
                }
                order_earlier_this_year = {
                    "id": "ord-earlier-year",
                    "orderNumber": "1003",
                    "createdAt": "2026-06-15T10:00:00Z",
                    "totalPrice": {"centAmount": 6000},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 5500},
                            "TotalDeposit": {"centAmount": 500},
                            "TotalDelivery": {"centAmount": 0},
                            "OfficialStatusIconState": "delivered",
                        }
                    },
                    "orderState": "Complete",
                }
                order_previous_year = {
                    "id": "ord-prev-year",
                    "orderNumber": "1004",
                    "createdAt": "2025-12-20T18:00:00Z",
                    "totalPrice": {"centAmount": 10000},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 9000},
                            "TotalDeposit": {"centAmount": 1000},
                            "TotalDelivery": {"centAmount": 0},
                            "OfficialStatusIconState": "delivered",
                        }
                    },
                    "orderState": "Complete",
                }
                order_cancelled_this_week = {
                    "id": "ord-cancelled",
                    "orderNumber": "1005",
                    "createdAt": "2026-11-03T18:00:00Z",
                    "totalPrice": {"centAmount": 5000},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 5000},
                            "TotalDeposit": {"centAmount": 0},
                            "TotalDelivery": {"centAmount": 0},
                            "OfficialStatusIconState": "cancelled",
                        }
                    },
                    "orderState": "Cancelled",
                }
                order_storniert_this_month = {
                    "id": "ord-storniert",
                    "orderNumber": "1006",
                    "createdAt": "2026-11-01T12:00:00Z",
                    "totalPrice": {"centAmount": 2500},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 2500},
                            "TotalDeposit": {"centAmount": 0},
                            "TotalDelivery": {"centAmount": 0},
                            "OfficialStatusIconState": "storniert",
                        }
                    },
                    "orderState": "Open",
                }

                all_test_orders = [
                    order_this_week,
                    order_earlier_this_month,
                    order_earlier_this_year,
                    order_previous_year,
                    order_cancelled_this_week,
                    order_storniert_this_month,
                ]

                # 1. Test SQLite storage upsert and retrieval
                await storage.async_record_orders(all_test_orders)
                recorded = await storage.async_get_all_recorded_orders()
                self.assertEqual(len(recorded), 6)

                # Test upsert conflict update
                updated_order = dict(order_this_week)
                updated_order["orderState"] = "UpdatedState"
                await storage.async_record_orders([updated_order])
                recorded_updated = await storage.async_get_all_recorded_orders()
                self.assertEqual(len(recorded_updated), 6)
                this_week_in_db = next(o for o in recorded_updated if o["id"] == "ord-this-week")
                self.assertEqual(this_week_in_db["orderState"], "UpdatedState")

                # Restore original
                await storage.async_record_orders([order_this_week])

                # 2. Test coordinator snapshot with all_orders populated
                coord.data = FlaschenpostSnapshot(
                    past_orders=[order_this_week, order_earlier_this_month],
                    all_orders=all_test_orders,
                )

                weekly_sensor = FlaschenpostWeeklySpentSensor(coord)
                monthly_sensor = FlaschenpostMonthlySpentSensor(coord)
                yearly_sensor = FlaschenpostYearlySpentSensor(coord)
                total_sensor = FlaschenpostTotalSpentSensor(coord)

                # Weekly spent: only order_this_week (45.50 EUR)
                self.assertEqual(weekly_sensor.native_value, 45.50)
                w_attrs = weekly_sensor.extra_state_attributes
                self.assertEqual(w_attrs["order_count"], 1)
                self.assertEqual(w_attrs["goods_eur"], 40.0)
                self.assertEqual(w_attrs["deposit_eur"], 2.50)
                self.assertEqual(w_attrs["delivery_fee_eur"], 3.0)
                self.assertEqual(len(w_attrs["recent_orders"]), 1)
                self.assertEqual(w_attrs["recent_orders"][0]["order_id"], "ord-this-week")

                # Monthly spent: order_this_week + order_earlier_this_month (45.50 + 30.00 = 75.50 EUR)
                self.assertEqual(monthly_sensor.native_value, 75.50)
                m_attrs = monthly_sensor.extra_state_attributes
                self.assertEqual(m_attrs["order_count"], 2)
                self.assertEqual(m_attrs["goods_eur"], 65.0)
                self.assertEqual(m_attrs["deposit_eur"], 7.50)
                self.assertEqual(m_attrs["delivery_fee_eur"], 3.0)
                self.assertEqual(len(m_attrs["recent_orders"]), 2)

                # Yearly spent: order_this_week + order_earlier_this_month + order_earlier_this_year (45.50 + 30.00 + 60.00 = 135.50 EUR)
                self.assertEqual(yearly_sensor.native_value, 135.50)
                y_attrs = yearly_sensor.extra_state_attributes
                self.assertEqual(y_attrs["order_count"], 3)
                self.assertEqual(y_attrs["goods_eur"], 120.0)
                self.assertEqual(y_attrs["deposit_eur"], 12.50)
                self.assertEqual(y_attrs["delivery_fee_eur"], 3.0)
                self.assertEqual(len(y_attrs["recent_orders"]), 3)

                # Total spent: all 4 non-cancelled orders (45.50 + 30.00 + 60.00 + 100.00 = 235.50 EUR)
                self.assertEqual(total_sensor.native_value, 235.50)
                t_attrs = total_sensor.extra_state_attributes
                self.assertEqual(t_attrs["order_count"], 4)
                self.assertEqual(t_attrs["goods_eur"], 210.0)
                self.assertEqual(t_attrs["deposit_eur"], 22.50)
                self.assertEqual(t_attrs["delivery_fee_eur"], 3.0)
                self.assertEqual(t_attrs["first_order_date"], "2025-12-20T18:00:00Z")
                self.assertEqual(t_attrs["last_order_date"], "2026-11-03T12:00:00Z")
                self.assertEqual(len(t_attrs["recent_orders"]), 4)

                # Empty snapshot test
                coord.data = FlaschenpostSnapshot()
                self.assertEqual(weekly_sensor.native_value, 0.0)
                self.assertEqual(monthly_sensor.native_value, 0.0)
                self.assertEqual(yearly_sensor.native_value, 0.0)
                self.assertEqual(total_sensor.native_value, 0.0)

                storage.close()

        asyncio.run(_run())

    def test_per_shopping_list_spending_summary_sensors(self) -> None:
        """Verify per-shopping-list spending summary sensors (weekly, monthly, yearly, total) and merged cart attribution."""
        import tempfile

        async def _run() -> None:
            fake_client = _FakeApiClient()
            mock_entry = types.SimpleNamespace(entry_id="test_entry", title="Test Account")
            mock_hass = types.SimpleNamespace(data={"flaschenpost": {}})

            with tempfile.TemporaryDirectory() as tmp_dir:
                db_path = Path(tmp_dir) / "flaschenpost.db"
                storage = FlaschenpostSqliteStorage(str(db_path))
                await storage.async_init()
                mgr = FlaschenpostShoppingListManager(client=fake_client, storage=storage)

                # 1. Create two lists and populate items
                await mgr.async_load()

                # Add items to "Weekly Grocery"
                # "1x Heidelbeeren" (art 29010 @ 2.29 EUR)
                # "2x Joghurt" (art 28435 @ 0.79 EUR = 1.58 EUR)
                await mgr.async_add_item("1x Heidelbeeren", list_name="Weekly Grocery")
                await mgr.async_add_item("2x Joghurt", list_name="Weekly Grocery")

                # Add items to "Office Drinks"
                # "1x Pepsi Zero" (crate, art 1838 @ 15.99 EUR)
                # "1x Joghurt" (merged with Weekly Grocery: art 28435 @ 0.79 EUR)
                await mgr.async_add_item("1 Kiste Pepsi Zero", list_name="Office Drinks")
                await mgr.async_add_item("1x Joghurt", list_name="Office Drinks")

                # 2. Sync both lists to cart (merged)
                sync_res = await mgr.async_add_lists_to_cart(
                    list_names=["Weekly Grocery", "Office Drinks"],
                    clear_cart_first=True,
                )
                self.assertEqual(sync_res["synced_count"], 3)  # Heidelbeeren, Joghurt (merged), Pepsi Zero

                # 3. Check SQLite cart attributions
                cart_attrs = await storage.async_get_cart_attributions()
                # 28435 (Joghurt) was requested by both lists: 2.0 by Weekly Grocery, 1.0 by Office Drinks
                self.assertIn(28435, cart_attrs)
                self.assertAlmostEqual(cart_attrs[28435]["Weekly Grocery"], 2.0)
                self.assertAlmostEqual(cart_attrs[28435]["Office Drinks"], 1.0)
                # 29010 (Heidelbeeren) only Weekly Grocery
                self.assertIn(29010, cart_attrs)
                self.assertAlmostEqual(cart_attrs[29010]["Weekly Grocery"], 1.0)
                # 1838 (Pepsi Zero) only Office Drinks
                self.assertIn(1838, cart_attrs)
                self.assertAlmostEqual(cart_attrs[1838]["Office Drinks"], 1.0)

                # 4. Simulate placing order
                # Total goods: 229 (Heidelbeeren) + 237 (3x Joghurt) + 1599 (Pepsi Zero) = 2065 cents (20.65 EUR)
                # Total deposit: 310 cents (3.10 EUR)
                # Delivery fee: 0 cents
                # Total price: 2375 cents (23.75 EUR)
                order_placed = {
                    "id": "ord-merged-001",
                    "orderNumber": "ORD-001",
                    "createdAt": "2026-11-03T12:00:00Z",  # This week (Wednesday is 2026-11-04)
                    "totalPrice": {"centAmount": 2375},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 2065},
                            "TotalDeposit": {"centAmount": 310},
                            "TotalDelivery": {"centAmount": 0},
                            "OfficialStatusIconState": "delivered",
                        }
                    },
                    "orderState": "Complete",
                    "lineItems": [
                        {
                            "id": "li-1",
                            "variant": {"sku": "29010"},
                            "name": {"de-DE": "K-Classic Heidelbeeren gezuckert"},
                            "quantity": 1,
                            "totalPrice": {"centAmount": 229},
                        },
                        {
                            "id": "li-2",
                            "variant": {"sku": "28435"},
                            "name": {"de-DE": "K-Classic Naturjoghurt 1,5%"},
                            "quantity": 3,
                            "totalPrice": {"centAmount": 237},
                        },
                        {
                            "id": "li-3",
                            "variant": {"sku": "1838"},
                            "name": {"de-DE": "Pepsi Zero Kiste"},
                            "quantity": 1,
                            "totalPrice": {"centAmount": 1599},
                        },
                    ],
                }

                await mgr.async_record_order_attributions(order_placed)

                # Cart attributions must be cleared after order
                cleared_attrs = await storage.async_get_cart_attributions()
                self.assertEqual(len(cleared_attrs), 0)

                # 5. Check order list spends in storage
                all_spends = await storage.async_get_all_list_spends()
                self.assertIn("Weekly Grocery", all_spends)
                self.assertIn("Office Drinks", all_spends)

                wg_spend = all_spends["Weekly Grocery"][0]
                od_spend = all_spends["Office Drinks"][0]

                # Weekly Grocery: 229 + 158 = 387 cents goods, 58 cents deposit -> 445 cents total (4.45 EUR)
                self.assertEqual(wg_spend["goods_cents"], 387)
                self.assertEqual(wg_spend["deposit_cents"], 58)
                self.assertEqual(wg_spend["total_cents"], 445)
                self.assertEqual(wg_spend["items_count"], 2)

                # Office Drinks: 1599 + 79 = 1678 cents goods, 252 cents deposit -> 1930 cents total (19.30 EUR)
                self.assertEqual(od_spend["goods_cents"], 1678)
                self.assertEqual(od_spend["deposit_cents"], 252)
                self.assertEqual(od_spend["total_cents"], 1930)
                self.assertEqual(od_spend["items_count"], 2)

                # Combined total matches order totalPrice exactly
                self.assertEqual(wg_spend["total_cents"] + od_spend["total_cents"], 2375)

                # 6. Setup coordinator & sensors
                coord = FlaschenpostCoordinator(
                    hass=mock_hass,  # type: ignore[arg-type]
                    entry=mock_entry,  # type: ignore[arg-type]
                    client=fake_client,  # type: ignore[arg-type]
                    shopping_list=mgr,
                )
                coord.data = FlaschenpostSnapshot(
                    list_spends=all_spends,
                    all_orders=[order_placed],
                )

                wg_weekly = FlaschenpostListWeeklySpentSensor(coord, "Weekly Grocery")
                wg_monthly = FlaschenpostListMonthlySpentSensor(coord, "Weekly Grocery")
                wg_yearly = FlaschenpostListYearlySpentSensor(coord, "Weekly Grocery")
                wg_total = FlaschenpostListTotalSpentSensor(coord, "Weekly Grocery")

                od_weekly = FlaschenpostListWeeklySpentSensor(coord, "Office Drinks")
                od_monthly = FlaschenpostListMonthlySpentSensor(coord, "Office Drinks")
                od_yearly = FlaschenpostListYearlySpentSensor(coord, "Office Drinks")
                od_total = FlaschenpostListTotalSpentSensor(coord, "Office Drinks")

                self.assertEqual(wg_weekly.native_value, 4.45)
                self.assertEqual(wg_monthly.native_value, 4.45)
                self.assertEqual(wg_yearly.native_value, 4.45)
                self.assertEqual(wg_total.native_value, 4.45)

                self.assertEqual(od_weekly.native_value, 19.30)
                self.assertEqual(od_monthly.native_value, 19.30)
                self.assertEqual(od_yearly.native_value, 19.30)
                self.assertEqual(od_total.native_value, 19.30)

                wg_attrs = wg_weekly.extra_state_attributes
                self.assertEqual(wg_attrs["list_name"], "Weekly Grocery")
                self.assertEqual(wg_attrs["order_count"], 1)
                self.assertEqual(wg_attrs["item_count"], 2)
                self.assertEqual(wg_attrs["goods_eur"], 3.87)
                self.assertEqual(wg_attrs["deposit_eur"], 0.58)
                self.assertEqual(wg_attrs["delivery_fee_eur"], 0.0)
                self.assertEqual(len(wg_attrs["recent_items"]), 2)

                # 7. Test cancelled order exclusion
                cancelled_order = {
                    "id": "ord-cancelled-999",
                    "orderNumber": "ORD-999",
                    "createdAt": "2026-11-03T14:00:00Z",
                    "totalPrice": {"centAmount": 5000},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 5000},
                            "OfficialStatusIconState": "cancelled",
                        }
                    },
                    "orderState": "Cancelled",
                    "lineItems": [
                        {
                            "id": "li-c",
                            "variant": {"sku": "29010"},
                            "name": {"de-DE": "K-Classic Heidelbeeren"},
                            "quantity": 1,
                            "totalPrice": {"centAmount": 5000},
                        }
                    ],
                }
                await storage.async_set_cart_attributions({29010: {"Weekly Grocery": 1.0}})
                await mgr.async_record_order_attributions(cancelled_order)

                await storage.async_record_orders([order_placed, cancelled_order])
                all_spends_with_cancelled = await storage.async_get_all_list_spends()
                coord.data = FlaschenpostSnapshot(
                    list_spends=all_spends_with_cancelled,
                    all_orders=[order_placed, cancelled_order],
                )

                self.assertEqual(wg_weekly.native_value, 4.45)
                self.assertEqual(wg_total.native_value, 4.45)

                # 8. Test dynamic sensor registration via async_setup_sensor_entry
                mock_hass.data["flaschenpost"]["test_entry"] = coord
                added_entities: list[Any] = []
                await async_setup_sensor_entry(
                    mock_hass,  # type: ignore[arg-type]
                    mock_entry,  # type: ignore[arg-type]
                    lambda entities: added_entities.extend(entities),
                )
                entity_keys = [getattr(e, "_period_key", None) for e in added_entities]
                self.assertIn("weekly_spent", entity_keys)
                self.assertIn("monthly_spent", entity_keys)
                self.assertIn("yearly_spent", entity_keys)
                self.assertIn("total_spent", entity_keys)
                list_sensor_names = [getattr(e, "_list_name", None) for e in added_entities]
                self.assertIn("Weekly Grocery", list_sensor_names)
                self.assertIn("Office Drinks", list_sensor_names)

                storage.close()

        asyncio.run(_run())

    def test_shopping_list_consume_items_on_order_and_event_entity(self) -> None:
        """Verify consumption of shopping list items upon order placement, both action types, and HA EventEntity updates."""
        import tempfile

        async def _run() -> None:
            fake_client = _FakeApiClient()
            mock_entry = types.SimpleNamespace(entry_id="test_entry", title="Test Account")
            fired_bus_events: list[tuple[str, dict[str, Any]]] = []

            class MockBus:
                def async_fire(self, event_name: str, event_data: dict[str, Any]) -> None:
                    fired_bus_events.append((event_name, event_data))

            mock_hass = types.SimpleNamespace(
                data={"flaschenpost": {}},
                bus=MockBus(),
            )

            with tempfile.TemporaryDirectory() as tmp_dir:
                db_path = Path(tmp_dir) / "flaschenpost.db"
                storage = FlaschenpostSqliteStorage(str(db_path))
                await storage.async_init()
                mgr = FlaschenpostShoppingListManager(client=fake_client, storage=storage)
                await mgr.async_load()

                # Configure lists:
                # ListA: consume_on_order=True, consume_action="complete"
                # ListB: consume_on_order=True, consume_action="delete"
                # ListC: consume_on_order=False (default)
                await mgr.async_set_list_config(
                    "ListA", consume_on_order=True, consume_action="complete"
                )
                await mgr.async_set_list_config(
                    "ListB", consume_on_order=True, consume_action="delete"
                )
                await mgr.async_set_list_config(
                    "ListC", consume_on_order=False
                )

                # Add items
                # ListA item: 1x Heidelbeeren (article 29010)
                item_a = await mgr.async_add_item("1x Heidelbeeren", list_name="ListA")
                # ListB item: 1x Joghurt (article 28435)
                item_b = await mgr.async_add_item("1x Joghurt", list_name="ListB")
                # ListC item: 1 Kiste Pepsi Zero (article 1838)
                item_c = await mgr.async_add_item("1 Kiste Pepsi Zero", list_name="ListC")

                # Sync lists to cart
                sync_res = await mgr.async_add_lists_to_cart(
                    list_names=["ListA", "ListB", "ListC"],
                    clear_cart_first=True,
                )
                self.assertEqual(sync_res["synced_count"], 3)

                # Check cart_list_items was stored
                cart_items = await storage.async_get_cart_list_items()
                self.assertEqual(len(cart_items), 3)
                tracked_uids = {it["item_uid"] for it in cart_items}
                self.assertIn(item_a.uid, tracked_uids)
                self.assertIn(item_b.uid, tracked_uids)
                self.assertIn(item_c.uid, tracked_uids)

                # Setup coordinator and event entities
                coord = FlaschenpostCoordinator(
                    hass=mock_hass,  # type: ignore[arg-type]
                    entry=mock_entry,  # type: ignore[arg-type]
                    client=fake_client,  # type: ignore[arg-type]
                    shopping_list=mgr,
                )
                mock_hass.data["flaschenpost"]["test_entry"] = coord

                event_entities: list[FlaschenpostListItemConsumedEventEntity] = []
                await async_setup_event_entry(
                    mock_hass,  # type: ignore[arg-type]
                    mock_entry,  # type: ignore[arg-type]
                    lambda entities: event_entities.extend(entities),
                )
                self.assertEqual(len(event_entities), 4)  # Default + ListA + ListB + ListC
                for ee in event_entities:
                    await ee.async_added_to_hass()

                entity_by_list = {ee._list_name: ee for ee in event_entities}
                self.assertIn("ListA", entity_by_list)
                self.assertIn("ListB", entity_by_list)
                self.assertIn("ListC", entity_by_list)

                # Simulate order placement with all 3 articles
                order_placed = {
                    "id": "ord-consume-101",
                    "orderNumber": "ORD-101",
                    "createdAt": "2026-11-04T12:00:00Z",
                    "totalPrice": {"centAmount": 2000},
                    "custom": {
                        "fields": {
                            "TotalGoods": {"centAmount": 2000},
                            "OfficialStatusIconState": "ready_for_delivery",
                        }
                    },
                    "orderState": "Open",
                    "lineItems": [
                        {
                            "id": "li-a",
                            "variant": {"sku": "29010"},
                            "name": {"de-DE": "K-Classic Heidelbeeren"},
                            "quantity": 1,
                            "totalPrice": {"centAmount": 229},
                        },
                        {
                            "id": "li-b",
                            "variant": {"sku": "28435"},
                            "name": {"de-DE": "Landliebe Joghurt"},
                            "quantity": 1,
                            "totalPrice": {"centAmount": 79},
                        },
                        {
                            "id": "li-c",
                            "variant": {"sku": "1838"},
                            "name": {"de-DE": "Pepsi Zero Kiste"},
                            "quantity": 1,
                            "totalPrice": {"centAmount": 1599},
                        },
                    ],
                }

                # Record attributions (which triggers consumption)
                await mgr.async_record_order_attributions(order_placed)

                # Verify ListA: item was completed
                items_a = mgr.get_list_items("ListA")
                self.assertEqual(len(items_a), 1)
                self.assertTrue(items_a[0].completed)

                # Verify ListB: item was deleted
                items_b = mgr.get_list_items("ListB")
                self.assertEqual(len(items_b), 0)

                # Verify ListC: consume_on_order=False, item remains uncompleted
                items_c = mgr.get_list_items("ListC")
                self.assertEqual(len(items_c), 1)
                self.assertFalse(items_c[0].completed)

                # Verify bus events fired: exactly 2 events (for ListA and ListB, but NOT ListC)
                self.assertEqual(len(fired_bus_events), 2)
                self.assertEqual(fired_bus_events[0][0], "flaschenpost_item_consumed")
                ev_a = fired_bus_events[0][1]
                self.assertEqual(ev_a["list_name"], "ListA")
                self.assertEqual(ev_a["item_uid"], item_a.uid)
                self.assertEqual(ev_a["action"], "complete")
                self.assertEqual(ev_a["order_id"], "ord-consume-101")
                self.assertEqual(ev_a["order_number"], "ORD-101")

                self.assertEqual(fired_bus_events[1][0], "flaschenpost_item_consumed")
                ev_b = fired_bus_events[1][1]
                self.assertEqual(ev_b["list_name"], "ListB")
                self.assertEqual(ev_b["item_uid"], item_b.uid)
                self.assertEqual(ev_b["action"], "delete")
                self.assertEqual(ev_b["order_id"], "ord-consume-101")
                self.assertEqual(ev_b["order_number"], "ORD-101")

                # Verify Event entities triggered
                ee_a = entity_by_list["ListA"]
                self.assertEqual(ee_a._last_event_type, "item_consumed")
                self.assertEqual(ee_a._last_event_attributes["item_uid"], item_a.uid)
                self.assertEqual(ee_a._last_event_attributes["action"], "complete")

                ee_b = entity_by_list["ListB"]
                self.assertEqual(ee_b._last_event_type, "item_consumed")
                self.assertEqual(ee_b._last_event_attributes["item_uid"], item_b.uid)
                self.assertEqual(ee_b._last_event_attributes["action"], "delete")

                ee_c = entity_by_list["ListC"]
                self.assertIsNone(getattr(ee_c, "_last_event_type", None))

                # Verify cart_list_items was cleared in storage
                cleared_cart_items = await storage.async_get_cart_list_items()
                self.assertEqual(len(cleared_cart_items), 0)

                # Verify idempotence: calling again for same order does not re-consume
                fired_count_before = len(fired_bus_events)
                second_res = await mgr.async_consume_order_items(order_placed)
                self.assertEqual(len(second_res), 0)
                self.assertEqual(len(fired_bus_events), fired_count_before)

                for ee in event_entities:
                    await ee.async_will_remove_from_hass()

                storage.close()

        asyncio.run(_run())

if __name__ == "__main__":
    unittest.main()
