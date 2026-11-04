"""DataUpdateCoordinator for the Flaschenpost integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FlaschenpostApiClient, FlaschenpostAuthError, FlaschenpostError
from .const import DOMAIN, SCAN_INTERVAL_ACTIVE_DELIVERY, SCAN_INTERVAL_IDLE
from .shopping_list import FlaschenpostShoppingListManager

_LOGGER = logging.getLogger(__name__)


@dataclass
class FlaschenpostSnapshot:
    """Aggregated state snapshot from Flaschenpost backend."""

    account: dict[str, Any] = field(default_factory=dict)
    cart: dict[str, Any] = field(default_factory=dict)
    active_orders: list[dict[str, Any]] = field(default_factory=list)
    tracked_order: dict[str, Any] | None = None
    past_orders: list[dict[str, Any]] = field(default_factory=list)
    past_orders_total: int = 0
    slots_response: dict[str, Any] = field(default_factory=dict)
    available_slots: list[dict[str, Any]] = field(default_factory=list)


class FlaschenpostCoordinator(DataUpdateCoordinator[FlaschenpostSnapshot]):
    """Coordinator managing polling and adaptive delivery tracking updates."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: FlaschenpostApiClient,
        shopping_list: FlaschenpostShoppingListManager,
    ) -> None:
        """Initialize the Flaschenpost coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.title}",
            update_interval=SCAN_INTERVAL_IDLE,
        )
        self.config_entry = entry
        self.client = client
        self.shopping_list = shopping_list
        self.last_update_success_time: datetime | None = None

    @property
    def next_update_time(self) -> datetime | None:
        """Return estimated timestamp of the next coordinator poll."""
        if self.last_update_success_time is None or self.update_interval is None:
            return None
        return self.last_update_success_time + self.update_interval

    async def _async_update_data(self) -> FlaschenpostSnapshot:
        """Fetch latest account, cart, active order tracking, history, and slots."""
        try:
            account = await self.client.async_get_my_account()
            cart = await self.client.async_get_cart()
            active_resp = await self.client.async_get_active_orders(offset=0)
            active_orders = active_resp.get("results") or []

            tracked_order: dict[str, Any] | None = None
            if active_orders:
                primary_id = active_orders[0].get("id")
                if primary_id:
                    try:
                        tracked_order = await self.client.async_get_order_tracking(
                            primary_id
                        )
                    except FlaschenpostError as err:
                        _LOGGER.debug(
                            "Live order tracking fallback to active order entry: %s",
                            err,
                        )
                        tracked_order = active_orders[0]

            past_resp = await self.client.async_get_past_orders(days=180, offset=0)
            past_orders = past_resp.get("results") or []
            past_total = int(past_resp.get("total") or len(past_orders))

            slots_resp = await self.client.async_get_delivery_slots(
                cart=cart, account=account
            )
            available_slots = self.client.pick_available_slots(slots_resp)

            # Speed up polling automatically while an active delivery is underway
            desired_interval = (
                SCAN_INTERVAL_ACTIVE_DELIVERY
                if active_orders
                else SCAN_INTERVAL_IDLE
            )
            if self.update_interval != desired_interval:
                self.update_interval = desired_interval

            self.last_update_success_time = dt_util.utcnow()

            return FlaschenpostSnapshot(
                account=account,
                cart=cart,
                active_orders=active_orders,
                tracked_order=tracked_order,
                past_orders=past_orders,
                past_orders_total=past_total,
                slots_response=slots_resp,
                available_slots=available_slots,
            )
        except FlaschenpostAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FlaschenpostError as err:
            raise UpdateFailed(f"Error communicating with Flaschenpost: {err}") from err
