"""To-Do / Shopping list platform for Flaschenpost."""

from __future__ import annotations

import re

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import cents_to_eur
from .const import DEFAULT_SHOPPING_LIST_NAME, DOMAIN, ORIGIN_CART, ORIGIN_SEARCH
from .coordinator import FlaschenpostCoordinator
from .entity import FlaschenpostEntity
from .shopping_list import (
    format_shopping_item_summary,
    parse_shopping_item_spec,
    parse_shopping_item_summary,
    resolve_sort_alias,
)


def _slugify_list_key(list_name: str) -> str:
    if list_name.strip().lower() == DEFAULT_SHOPPING_LIST_NAME.lower():
        return "shopping_list"
    slug = re.sub(r"[^a-z0-9]+", "_", list_name.strip().lower()).strip("_")
    return f"shopping_list_{slug or 'custom'}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Flaschenpost Named Shopping Lists and Live Cart To-Do entities."""
    coordinator: FlaschenpostCoordinator = hass.data[DOMAIN][entry.entry_id]
    registered_keys: set[str] = set()

    initial_entities: list[TodoListEntity] = [FlaschenpostCartTodoEntity(coordinator)]
    for lname in coordinator.shopping_list.list_names:
        key = _slugify_list_key(lname)
        if key not in registered_keys:
            registered_keys.add(key)
            initial_entities.append(
                FlaschenpostShoppingListTodoEntity(coordinator, lname)
            )

    async_add_entities(initial_entities)

    @callback
    def _on_new_list_created(new_list_name: str) -> None:
        key = _slugify_list_key(new_list_name)
        if key in registered_keys:
            return
        registered_keys.add(key)
        async_add_entities(
            [FlaschenpostShoppingListTodoEntity(coordinator, new_list_name)]
        )

    coordinator.shopping_list.register_list_added_callback(_on_new_list_created)


class FlaschenpostShoppingListTodoEntity(FlaschenpostEntity, TodoListEntity):
    """Persistent Home Assistant Flaschenpost shopping list (lazily resolved at order/cart time)."""

    _attr_icon = "mdi:clipboard-list-outline"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(
        self,
        coordinator: FlaschenpostCoordinator,
        list_name: str = DEFAULT_SHOPPING_LIST_NAME,
    ) -> None:
        key = _slugify_list_key(list_name)
        super().__init__(coordinator, key)
        self._list_name = list_name
        if list_name.strip().lower() == DEFAULT_SHOPPING_LIST_NAME.lower():
            self._attr_translation_key = "shopping_list"
        else:
            self._attr_name = f"Shopping list: {list_name}"

    @property
    def todo_items(self) -> list[TodoItem]:
        items: list[TodoItem] = []
        for entry in self.coordinator.shopping_list.get_list_items(self._list_name):
            items.append(
                TodoItem(
                    uid=entry.uid,
                    summary=entry.summary,
                    description=entry.last_resolved_note,
                    status=(
                        TodoItemStatus.COMPLETED
                        if entry.completed
                        else TodoItemStatus.NEEDS_ACTION
                    ),
                )
            )
        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        await self.coordinator.shopping_list.async_add_item(
            summary=item.summary or "",
            description=item.description,
            list_name=self._list_name,
        )
        self.async_write_ha_state()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if not item.uid:
            return
        completed = (
            item.status == TodoItemStatus.COMPLETED
            if item.status is not None
            else None
        )
        await self.coordinator.shopping_list.async_update_item(
            item.uid,
            summary=item.summary,
            completed=completed,
            list_name=self._list_name,
        )
        self.async_write_ha_state()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        await self.coordinator.shopping_list.async_remove_items(
            uids, list_name=self._list_name
        )
        self.async_write_ha_state()


class FlaschenpostCartTodoEntity(FlaschenpostEntity, TodoListEntity):
    """Live To-Do list directly bound to the remote Flaschenpost shopping cart."""

    _attr_translation_key = "cart"
    _attr_icon = "mdi:cart-outline"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: FlaschenpostCoordinator) -> None:
        super().__init__(coordinator, "cart")

    @property
    def todo_items(self) -> list[TodoItem]:
        items: list[TodoItem] = []
        for li in self.coordinator.data.cart.get("lineItems") or []:
            line_id = str(li.get("id") or "")
            sku_raw = (li.get("variant") or {}).get("sku")
            aid = int(sku_raw) if sku_raw and str(sku_raw).isdigit() else None
            qty = int(li.get("quantity") or 1)
            name_obj = li.get("name") or {}
            name = (
                name_obj.get("de-DE") or next(iter(name_obj.values()), "")
                if isinstance(name_obj, dict)
                else str(name_obj)
            )
            total_eur = cents_to_eur(li.get("totalPrice"))
            items.append(
                TodoItem(
                    uid=line_id,
                    summary=format_shopping_item_summary(qty, name, aid),
                    description=f"Total: {total_eur:.2f} EUR",
                    status=TodoItemStatus.NEEDS_ACTION,
                )
            )
        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        spec = parse_shopping_item_spec(item.summary or "")
        desc_sort = resolve_sort_alias(item.description) if item.description else None
        sort_by = spec.sort_by or desc_sort

        resolution = await self.coordinator.client.async_resolve_item_for_cart(
            spec.query,
            category=spec.category,
            unit_type=spec.unit_type,
            target_amount_base=spec.target_amount_base,
            article_id=spec.explicit_article_id,
            sort_by=sort_by,
        )
        if not resolution or resolution.get("article_id") is None:
            raise HomeAssistantError(
                f"No Flaschenpost product found in warehouse for '{item.summary}'"
            )
        aid = int(resolution["article_id"])
        qty = int(resolution["quantity"])

        existing_qty = 0
        for li in self.coordinator.data.cart.get("lineItems") or []:
            if str((li.get("variant") or {}).get("sku")) == str(aid):
                existing_qty = int(li.get("quantity") or 0)
                break

        await self.coordinator.client.async_set_cart_positions(
            [
                {
                    "articleId": aid,
                    "origin": ORIGIN_SEARCH,
                    "quantityTotal": existing_qty + qty,
                }
            ]
        )
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if not item.uid:
            return
        if item.status == TodoItemStatus.COMPLETED:
            await self.coordinator.client.async_remove_line_item(item.uid)
            await self.coordinator.async_request_refresh()
            return

        if item.summary:
            qty, _query, aid = parse_shopping_item_summary(item.summary)
            if aid is None:
                for li in self.coordinator.data.cart.get("lineItems") or []:
                    if li.get("id") == item.uid:
                        sku = (li.get("variant") or {}).get("sku")
                        if sku and str(sku).isdigit():
                            aid = int(sku)
                        break
            if aid is not None:
                await self.coordinator.client.async_set_cart_positions(
                    [
                        {
                            "articleId": aid,
                            "origin": ORIGIN_CART,
                            "quantityTotal": qty,
                        }
                    ]
                )
                await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        for uid in uids:
            await self.coordinator.client.async_remove_line_item(uid)
        await self.coordinator.async_request_refresh()
