"""Sensor entities for active order tracking, live delivery, history, cart & slots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import cents_to_eur
from .const import DOMAIN
from .coordinator import FlaschenpostCoordinator
from .entity import FlaschenpostEntity


def _summarize_order(order: dict[str, Any]) -> dict[str, Any]:
    """Build compact HA attribute summary for an order object."""
    custom_fields = (order.get("custom") or {}).get("fields") or {}
    ship_fields = (order.get("shippingCustomFields") or {}).get("fields") or {}
    deliveries = (order.get("shippingInfo") or {}).get("deliveries") or []
    deliv_fields = (
        ((deliveries[0].get("custom") or {}).get("fields") or {})
        if deliveries
        else {}
    )
    items = []
    for li in order.get("lineItems") or []:
        name_obj = li.get("name") or {}
        name = (
            name_obj.get("de-DE") or next(iter(name_obj.values()), "")
            if isinstance(name_obj, dict)
            else str(name_obj)
        )
        items.append(
            {
                "article_id": (li.get("variant") or {}).get("sku"),
                "name": name,
                "quantity": li.get("quantity"),
                "total_eur": cents_to_eur(li.get("totalPrice")),
            }
        )

    return {
        "order_id": order.get("id"),
        "order_number": order.get("orderNumber"),
        "created_at": order.get("createdAt"),
        "status": custom_fields.get("OfficialStatusIconState"),
        "status_message": custom_fields.get("OfficialStatusMessage"),
        "eta_from": custom_fields.get("OfficialStatusETAFrom")
        or ship_fields.get("SelectedDeliveryFrom"),
        "eta_until": custom_fields.get("OfficialStatusETAUntil")
        or ship_fields.get("SelectedDeliveryUntil"),
        "delivery_type": ship_fields.get("SelectedDeliveryType"),
        "stops_remaining": deliv_fields.get("CurrentStopsBeforeArrival"),
        "actual_delivery_time": deliv_fields.get("ActualTimeOfDelivery"),
        "total_eur": cents_to_eur(order.get("totalPrice")),
        "goods_eur": cents_to_eur(custom_fields.get("TotalGoods")),
        "deposit_eur": cents_to_eur(custom_fields.get("TotalDeposit")),
        "delivery_fee_eur": cents_to_eur(custom_fields.get("TotalDelivery")),
        "items": items,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Flaschenpost sensor entities."""
    coordinator: FlaschenpostCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            FlaschenpostOrderStatusSensor(coordinator),
            FlaschenpostStopsRemainingSensor(coordinator),
            FlaschenpostDeliveryEtaSensor(coordinator),
            FlaschenpostOrderHistorySensor(coordinator),
            FlaschenpostCartTotalSensor(coordinator),
            FlaschenpostNextSlotSensor(coordinator),
        ]
    )


class FlaschenpostOrderStatusSensor(FlaschenpostEntity, SensorEntity):
    """Current active order & live delivery tracking status sensor."""

    _attr_translation_key = "order_status"
    _attr_icon = "mdi:truck-delivery"

    def __init__(self, coordinator: FlaschenpostCoordinator) -> None:
        super().__init__(coordinator, "order_status")

    @property
    def native_value(self) -> str:
        order = self.coordinator.data.tracked_order
        if not order:
            return "idle"
        fields = (order.get("custom") or {}).get("fields") or {}
        return str(fields.get("OfficialStatusIconState") or "active")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        order = self.coordinator.data.tracked_order
        if not order:
            return {"active_orders_count": 0}
        attrs = _summarize_order(order)
        attrs["active_orders_count"] = len(self.coordinator.data.active_orders)
        return attrs


class FlaschenpostStopsRemainingSensor(FlaschenpostEntity, SensorEntity):
    """Number of stops remaining before the delivery driver arrives."""

    _attr_translation_key = "stops_remaining"
    _attr_icon = "mdi:map-marker-distance"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FlaschenpostCoordinator) -> None:
        super().__init__(coordinator, "stops_remaining")

    @property
    def native_value(self) -> int | None:
        order = self.coordinator.data.tracked_order
        if not order:
            return None
        deliveries = (order.get("shippingInfo") or {}).get("deliveries") or []
        if not deliveries:
            return None
        stops = (
            (deliveries[0].get("custom") or {})
            .get("fields", {})
            .get("CurrentStopsBeforeArrival")
        )
        return int(stops) if stops is not None else None


class FlaschenpostDeliveryEtaSensor(FlaschenpostEntity, SensorEntity):
    """Live delivery ETA start timestamp sensor."""

    _attr_translation_key = "delivery_eta"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-fast"

    def __init__(self, coordinator: FlaschenpostCoordinator) -> None:
        super().__init__(coordinator, "delivery_eta")

    @property
    def native_value(self) -> datetime | None:
        order = self.coordinator.data.tracked_order
        if not order:
            return None
        c_fields = (order.get("custom") or {}).get("fields") or {}
        s_fields = (order.get("shippingCustomFields") or {}).get("fields") or {}
        eta_str = c_fields.get("OfficialStatusETAFrom") or s_fields.get(
            "SelectedDeliveryFrom"
        )
        if not eta_str:
            return None
        return dt_util.parse_datetime(str(eta_str))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        order = self.coordinator.data.tracked_order
        if not order:
            return {}
        c_fields = (order.get("custom") or {}).get("fields") or {}
        s_fields = (order.get("shippingCustomFields") or {}).get("fields") or {}
        return {
            "eta_until": c_fields.get("OfficialStatusETAUntil")
            or s_fields.get("SelectedDeliveryUntil"),
            "status_message": c_fields.get("OfficialStatusMessage"),
        }


class FlaschenpostOrderHistorySensor(FlaschenpostEntity, SensorEntity):
    """Customer order history count & recent orders summary."""

    _attr_translation_key = "order_history"
    _attr_icon = "mdi:history"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: FlaschenpostCoordinator) -> None:
        super().__init__(coordinator, "order_history")

    @property
    def native_value(self) -> int:
        acc_fields = (
            (self.coordinator.data.account.get("custom") or {}).get("fields") or {}
        )
        delivered = acc_fields.get("DeliveredOrders")
        if delivered is not None:
            return int(delivered)
        return self.coordinator.data.past_orders_total

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        past = self.coordinator.data.past_orders
        recent = [_summarize_order(o) for o in past[:5]]
        return {
            "last_180d_count": self.coordinator.data.past_orders_total,
            "last_order": recent[0] if recent else None,
            "recent_orders": recent,
        }


class FlaschenpostCartTotalSensor(FlaschenpostEntity, SensorEntity):
    """Current shopping cart total in EUR."""

    _attr_translation_key = "cart_total"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_EURO
    _attr_icon = "mdi:cart"

    def __init__(self, coordinator: FlaschenpostCoordinator) -> None:
        super().__init__(coordinator, "cart_total")

    @property
    def native_value(self) -> float:
        return cents_to_eur(self.coordinator.data.cart.get("totalPrice"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cart = self.coordinator.data.cart
        c_fields = (cart.get("custom") or {}).get("fields") or {}
        s_fields = (cart.get("shippingCustomFields") or {}).get("fields") or {}
        items = []
        for li in cart.get("lineItems") or []:
            name_obj = li.get("name") or {}
            name = (
                name_obj.get("de-DE") or next(iter(name_obj.values()), "")
                if isinstance(name_obj, dict)
                else str(name_obj)
            )
            items.append(
                {
                    "line_item_id": li.get("id"),
                    "article_id": (li.get("variant") or {}).get("sku"),
                    "name": name,
                    "quantity": li.get("quantity"),
                    "total_eur": cents_to_eur(li.get("totalPrice")),
                }
            )
        return {
            "cart_id": cart.get("id"),
            "item_count": cart.get("totalLineItemQuantity", 0),
            "warehouse_id": c_fields.get("RecentlyUsedWarehouseId"),
            "goods_eur": cents_to_eur(c_fields.get("TotalGoods")),
            "deposit_eur": cents_to_eur(c_fields.get("TotalDeposit")),
            "delivery_fee_eur": cents_to_eur(c_fields.get("TotalDelivery")),
            "selected_slot_type": s_fields.get("SelectedDeliveryType"),
            "selected_slot_from": s_fields.get("SelectedDeliveryFrom"),
            "selected_slot_until": s_fields.get("SelectedDeliveryUntil"),
            "items": items,
        }


class FlaschenpostNextSlotSensor(FlaschenpostEntity, SensorEntity):
    """Earliest available delivery slot timestamp."""

    _attr_translation_key = "next_delivery_slot"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: FlaschenpostCoordinator) -> None:
        super().__init__(coordinator, "next_delivery_slot")

    @property
    def native_value(self) -> datetime | None:
        slots = self.coordinator.data.available_slots
        if not slots:
            return None
        first_from = slots[0].get("from")
        if not first_from:
            return None
        return dt_util.parse_datetime(str(first_from))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slots = self.coordinator.data.available_slots
        resp = self.coordinator.data.slots_response
        comm = resp.get("shopCommunication") or {}
        return {
            "shop_state": resp.get("shopState"),
            "communicated_delivery_time_min": comm.get("communicatedDeliveryTime"),
            "next_slot": slots[0] if slots else None,
            "available_slots": [
                {
                    "type": s.get("type"),
                    "from": s.get("from"),
                    "until": s.get("until"),
                    "window": s.get("window"),
                }
                for s in slots[:10]
            ],
        }
