# Automated Cart Filling with Flaschenpost

This guide demonstrates how to automate populating your Flaschenpost shopping cart using Home Assistant automations.

---

## Capabilities

With the `flaschenpost.add_shopping_lists_to_cart` service, you can:
- **Merge N shopping lists** dynamically (e.g. household basics, office drinks, weekly meal plans, Bring lists).
- **Resolve cheapest product lazily at order time** based on warehouse real-time stock and prices.
- **Support alternating schedules** using Jinja templates (e.g. even vs. odd calendar weeks).
- **Choose sort strategies per sync**:
  - `price`: Overall cheapest item (default).
  - `price_per_kg`: Cheapest price per kilogram (great for pantry dry goods, rice, flour, fruit).
  - `price_per_liter`: Cheapest price per liter (great for milk, juices, mineral water).
  - `price_per_unit`: Cheapest price per piece.
  - `relevance`: Match search ranking.
- **Inspect unresolved items** (e.g. items out of stock) via the service `response_variable`.

---

## Service Parameters

```yaml
action: flaschenpost.add_shopping_lists_to_cart
data:
  shopping_lists:
    - "Grundvorräte"
    - "Getränke"
    - "todo.bring_einkaufsliste"
  clear_cart_first: true      # Set to true to start with an empty cart
  mark_completed: false       # Set to true to mark items as done after adding to cart
  default_sort_by: price      # price, price_per_kg, price_per_liter, price_per_unit
```

---

## Service Response Variable Structure

When using `response_variable: cart_result`, the service returns:

```json
{
  "lists_merged": ["Grundvorräte", "Getränke"],
  "synced_count": 8,
  "resolved_items": [
    {
      "name": "Landliebe Frische Vollmilch",
      "article_id": 28435,
      "quantity_added": 2,
      "unit_price_eur": 1.59,
      "line_total_eur": 3.18
    }
  ],
  "unresolved": [
    "Bio Avocados"
  ],
  "cart_id": "cart-uuid"
}
```

---

## Ready-to-Use Automations

See [`automations.yaml`](./automations.yaml) for:
1. **Scheduled weekly cart filling** (e.g., every Thursday evening before delivery day), which sends a mobile push notification with the cart total and any out-of-stock items.
2. **On-demand button replenishment** to top up drinks and pantry essentials with one tap.
