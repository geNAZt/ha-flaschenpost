"""WebSocket API commands for Flaschenpost interactive shopping lists and warehouse search."""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEFAULT_PAYMENT,
    CONF_IBAN_LAST4,
    CONF_STORED_PAYMENT_ID,
    DOMAIN,
    PAYMENT_CREDIT_CARD,
)

_LOGGER = logging.getLogger(__name__)


def _serialize_obj(obj: Any) -> Any:
    """Recursively serialize dataclasses, sets, or nested objects for JSON WebSocket responses."""
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _serialize_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_obj(x) for x in obj]
    if isinstance(obj, set):
        return [_serialize_obj(x) for x in obj]
    return obj


def _resolve_coord(hass: HomeAssistant, config_entry_id: str | None = None) -> Any:
    """Resolve active Flaschenpost coordinator."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ValueError("No Flaschenpost integration is configured or loaded")
    if config_entry_id:
        coord = entries.get(config_entry_id)
        if not coord:
            raise ValueError(f"Flaschenpost config_entry_id '{config_entry_id}' not found")
        return coord
    return next(iter(entries.values()))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/get_lists",
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_lists(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Fetch all managed shopping lists and their items."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        lists = coord.shopping_list.get_all_lists_dict()
        names = coord.shopping_list.list_names
        connection.send_result(msg["id"], {"lists": lists, "names": names})
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/get_lists: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/save_list",
        vol.Required("name"): str,
        vol.Required("items"): list,
        vol.Optional("replace", default=True): bool,
        vol.Optional("sort_by"): vol.Any(None, str),
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_save_list(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Save or replace a full named shopping list."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        name = str(msg["name"]).strip()
        lines = [str(x) for x in msg["items"]]
        saved = await coord.shopping_list.async_save_named_list(
            name, lines, replace=bool(msg.get("replace", True)), sort_by=msg.get("sort_by")
        )
        coord.async_update_listeners()
        connection.send_result(
            msg["id"],
            {
                "name": name,
                "item_count": len(saved),
                "items": [it.to_dict() for it in saved],
                "names": coord.shopping_list.list_names,
            },
        )
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/save_list: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/delete_list",
        vol.Required("name"): str,
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_list(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a named shopping list."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        name = str(msg["name"]).strip()
        deleted = await coord.shopping_list.async_delete_named_list(name)
        coord.async_update_listeners()
        connection.send_result(
            msg["id"],
            {
                "name": name,
                "deleted": deleted,
                "names": coord.shopping_list.list_names,
            },
        )
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/delete_list: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/add_item",
        vol.Required("list_name"): str,
        vol.Required("summary"): str,
        vol.Optional("description"): str,
        vol.Optional("sort_by"): vol.Any(None, str),
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_add_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a single item to a shopping list."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        lname = str(msg["list_name"]).strip()
        summary = str(msg["summary"]).strip()
        item = await coord.shopping_list.async_add_item(
            summary,
            description=msg.get("description"),
            sort_by=msg.get("sort_by"),
            list_name=lname,
        )
        coord.async_update_listeners()
        connection.send_result(
            msg["id"],
            {
                "item": item.to_dict(),
                "list_name": lname,
                "items": [it.to_dict() for it in coord.shopping_list.get_list_items(lname)],
            },
        )
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/add_item: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/update_item",
        vol.Required("list_name"): str,
        vol.Required("uid"): str,
        vol.Optional("summary"): str,
        vol.Optional("completed"): bool,
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_update_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update an item's text/amount or completed status."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        lname = str(msg["list_name"]).strip()
        uid = str(msg["uid"]).strip()
        item = await coord.shopping_list.async_update_item(
            uid,
            summary=msg.get("summary"),
            completed=msg.get("completed"),
            list_name=lname,
        )
        coord.async_update_listeners()
        connection.send_result(
            msg["id"],
            {
                "item": item.to_dict() if item else None,
                "list_name": lname,
                "items": [it.to_dict() for it in coord.shopping_list.get_list_items(lname)],
            },
        )
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/update_item: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/delete_item",
        vol.Required("list_name"): str,
        vol.Required("uids"): list,
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove items by UID from a named shopping list."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        lname = str(msg["list_name"]).strip()
        uids = [str(u) for u in msg["uids"]]
        await coord.shopping_list.async_remove_items(uids, list_name=lname)
        coord.async_update_listeners()
        connection.send_result(
            msg["id"],
            {
                "deleted_uids": uids,
                "list_name": lname,
                "items": [it.to_dict() for it in coord.shopping_list.get_list_items(lname)],
            },
        )
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/delete_item: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/preview_search",
        vol.Required("query"): str,
        vol.Optional("amount_prefix"): vol.Any(None, str),
        vol.Optional("category"): vol.Any(None, str),
        vol.Optional("sort_by"): vol.Any(None, str),
        vol.Optional("limit", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_preview_search(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run an interactive live preview search with candidate comparison table and winner."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        query = str(msg["query"]).strip()
        if not query:
            connection.send_result(
                msg["id"],
                {
                    "candidates": [],
                    "winner": None,
                    "lazy_summary": "",
                    "markdown": "",
                },
            )
            return

        res = await coord.shopping_list.async_preview_search(
            query,
            amount_prefix=msg.get("amount_prefix"),
            category=msg.get("category"),
            sort_by=msg.get("sort_by"),
            limit=int(msg.get("limit", 10)),
        )
        connection.send_result(msg["id"], _serialize_obj(res))
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/preview_search: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/preview_lists",
        vol.Optional("shopping_lists"): list,
        vol.Optional("default_sort_by"): vol.Any(None, str),
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_preview_lists(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run a dry-run cart resolution preview across 1..N shopping lists."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        lists = [str(x) for x in msg["shopping_lists"]] if msg.get("shopping_lists") else None
        res = await coord.shopping_list.async_preview_lists(
            list_names=lists,
            default_sort_by=msg.get("default_sort_by"),
        )
        connection.send_result(msg["id"], _serialize_obj(res))
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/preview_lists: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/get_categories",
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_categories(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get category options for dropdown filtering."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        options = await coord.shopping_list.async_get_category_options()
        connection.send_result(msg["id"], {"options": options})
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/get_categories: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/get_cart",
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_cart(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get current active Flaschenpost cart status, line items, and minimum order progress."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        cart = await coord.client.async_get_cart()
        items = []
        for li in cart.get("lineItems") or []:
            prod = li.get("product") or {}
            variant = li.get("variant") or {}
            p_price = ((li.get("price") or {}).get("value") or {}).get("centAmount") or 0
            items.append(
                {
                    "article_id": variant.get("sku"),
                    "name": (prod.get("name") or {}).get("de") or prod.get("name") or "Produkt",
                    "quantity": li.get("quantity") or 1,
                    "unit_price_eur": round(p_price / 100.0, 2),
                    "total_eur": round((p_price * (li.get("quantity") or 1)) / 100.0, 2),
                }
            )

        total_price = ((cart.get("totalPrice") or {}).get("centAmount") or 0) / 100.0
        shipping_fee = (
            ((cart.get("shippingInfo") or {}).get("price") or {}).get("centAmount") or 0
        )
        custom_fields = (cart.get("custom") or {}).get("fields") or {}
        min_order = (custom_fields.get("MinimumOrderValue") or 2500) / 100.0
        connection.send_result(
            msg["id"],
            {
                "cart_id": cart.get("id"),
                "items": items,
                "total_eur": round(total_price, 2),
                "shipping_fee_eur": round(shipping_fee / 100.0, 2),
                "min_order_value_eur": round(min_order, 2),
                "min_order_reached": total_price >= min_order,
                "remaining_to_min_eur": round(max(0.0, min_order - total_price), 2),
            },
        )
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/get_cart: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/sync_to_cart",
        vol.Optional("shopping_lists"): list,
        vol.Optional("clear_cart_first", default=False): bool,
        vol.Optional("mark_completed", default=False): bool,
        vol.Optional("default_sort_by"): vol.Any(None, str),
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_sync_to_cart(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Sync specified shopping lists into live Flaschenpost cart."""
    try:
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        lists = [str(x) for x in msg["shopping_lists"]] if msg.get("shopping_lists") else None
        res = await coord.shopping_list.async_add_lists_to_cart(
            list_names=lists,
            clear_cart_first=bool(msg.get("clear_cart_first", False)),
            mark_completed=bool(msg.get("mark_completed", False)),
            default_sort_by=msg.get("default_sort_by"),
        )
        await coord.async_request_refresh()
        connection.send_result(msg["id"], _serialize_obj(res))
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/sync_to_cart: %s", err)
        connection.send_error(msg["id"], "error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "flaschenpost/buy_cart",
        vol.Required("confirm"): bool,
        vol.Optional("payment_method"): str,
        vol.Optional("stored_payment_id"): str,
        vol.Optional("iban_last4"): str,
        vol.Optional("slot_type"): str,
        vol.Optional("slot_from"): str,
        vol.Optional("config_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_buy_cart(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Submit purchase for current live cart."""
    try:
        if not msg.get("confirm"):
            connection.send_error(msg["id"], "unconfirmed", "Payment confirmation required")
            return
        coord = _resolve_coord(hass, msg.get("config_entry_id"))
        opts = coord.config_entry.options
        data = coord.config_entry.data
        payment_method = (
            msg.get("payment_method")
            or opts.get(CONF_DEFAULT_PAYMENT)
            or data.get(CONF_DEFAULT_PAYMENT, PAYMENT_CREDIT_CARD)
        )
        stored_payment_id = (
            msg.get("stored_payment_id")
            or opts.get(CONF_STORED_PAYMENT_ID)
            or data.get(CONF_STORED_PAYMENT_ID)
            or None
        )
        iban_last4 = (
            msg.get("iban_last4")
            or opts.get(CONF_IBAN_LAST4)
            or data.get(CONF_IBAN_LAST4)
            or None
        )
        order = await coord.client.async_place_order(
            payment_method=payment_method,
            iban_last4=iban_last4,
            stored_payment_id=stored_payment_id,
            slot_type=msg.get("slot_type"),
            slot_from=msg.get("slot_from"),
        )
        await coord.async_request_refresh()
        connection.send_result(
            msg["id"],
            {
                "order_id": order.get("id"),
                "order_number": order.get("orderNumber"),
            },
        )
    except Exception as err:
        _LOGGER.exception("Error in flaschenpost/buy_cart: %s", err)
        connection.send_error(msg["id"], "error", str(err))


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all Flaschenpost WebSocket commands."""
    commands = [
        ws_get_lists,
        ws_save_list,
        ws_delete_list,
        ws_add_item,
        ws_update_item,
        ws_delete_item,
        ws_preview_search,
        ws_preview_lists,
        ws_get_categories,
        ws_get_cart,
        ws_sync_to_cart,
        ws_buy_cart,
    ]
    for cmd in commands:
        websocket_api.async_register_command(hass, cmd)
