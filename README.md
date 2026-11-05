# Flaschenpost for Home Assistant (HACS)

Custom Home Assistant integration for **flaschenpost.de** supporting **interactive delivery map & warehouse verification**, **named recurring shopping lists & multi-list merging**, **interactive preview search with simulated pack counts during configuration**, **category filters (`Category::Product`)**, **amount/unit math (`kg`, `g`, `L`, `ml`, `Kiste`)**, **lazy cheapest-at-order-time product resolution**, **product search by Name / Category / €/unit / €/kg / €/L**, **live cart synchronization**, **headless ordering**, **active order & live delivery tracking**, and **order history**.

## Features

### Interactive Delivery Map & Warehouse Assignment
During setup (and reconfigurable anytime via Options):
- **Interactive Map Picker**: An interactive map pin (`LocationSelector`) centered by default on your Home Assistant home coordinates (`latitude` / `longitude`), or your saved Flaschenpost profile address coordinates.
- **Delivery Area Polygon Check**: Automatically verifies against Flaschenpost's polygon delivery boundaries (`/webshop-checkout-api/api/v2/address/isInPolygonDeliveryArea/{lat},{lon}`).
- **Warehouse Auto-Discovery & Sync**: Triggers Flaschenpost cart polygon recalculation (`/webshop-cart-api/api/v4/refreshPolygonProperties`) to automatically bind and confirm the exact local warehouse ID (e.g. `27`) serving your coordinates, ensuring you get real stock and prices for your location.

### Integration Configuration & Interactive Preview Search
During integration setup (or anytime afterwards via **Configure** in Home Assistant -> Settings -> Devices & Services):
- **Interactive Preview Search**: Type a search query (e.g. `Milchreis`, `Naturjoghurt`, `Pepsi Zero`), an optional target amount (e.g. `500g`, `1kg`, `1,5kg`, `1 Kiste`), an optional category filter (`Reis & Getreide`), and sort mode (`auto`, `€/kg`, `€/L`, `€/unit`, `price`, `relevance`).
- **Live Warehouse Simulation**: Flaschenpost stock, prices, and pack weights/volumes are fetched directly from your local warehouse. The flow renders:
  - The current **lazy order-time winner** (unit price, €/kg or €/L, and category path).
  - Exact **pack count calculations** needed to reach your target minimum (e.g. `2x 400g = 800g` for `500g` dry rice, or `2x 4x150g = 1,2kg` for `1kg` yogurt).
  - A ranked comparison table of all available alternatives in your warehouse with live stock indicators.
- **One-Click Add**: Add the item directly to any named list (`Every week`, `Every even week`, `Every odd week`, or a brand-new list) as a **flexible lazy requirement** or as a **pinned product (`#article_id`)**.
- **Saved Payment Methods Discovery**: Fetches saved payment instruments directly from your Flaschenpost profile (saved Credit Cards via Adyen, saved PayPal billing agreements, and saved SEPA mandates) so you can choose your preferred card or payment method directly from a dropdown in **Configure -> Payment & ordering preferences**.
- **Multiline List Editor & Dry-Run Cart Preview**: Edit or paste entire shopping lists and see a live dry-run summary with estimated basket totals before adding anything to your real cart.

### Entities
- **Binary Sensor:**
  - `binary_sensor.flaschenpost_active_delivery` — `on` while an order is in progress (switches from 5-minute idle polling to 60-second live delivery polling).
- **Sensors:**
  - `sensor.flaschenpost_order_status` — `idle`, `OrderPlaced`, `PickingStarted`, `OrderLeftWarehouse`, `SuccessfullyDelivered`, or `Cancelled` achievements.
  - `sensor.flaschenpost_stops_remaining` — Number of stops remaining before the driver arrives.
  - `sensor.flaschenpost_delivery_eta` — Live delivery window start timestamp (`eta_until` in attributes).
  - `sensor.flaschenpost_delivered_orders` — Total delivered orders count with `last_order` and `recent_orders` history.
  - `sensor.flaschenpost_cart_total` — Current cart total in `EUR` (`goods_eur`, `deposit_eur`, `delivery_fee_eur`, `items`, and selected slot).
  - `sensor.flaschenpost_next_delivery_slot` — Earliest open delivery window (`available_slots` & `shop_state`).
- **To-Do / Shopping Lists (`todo`):**
  - `todo.flaschenpost_shopping_list` (plus dynamic `todo.flaschenpost_shopping_list_<name>` entities for every named list) — Stores item requirements lazily (`1kg Naturjoghurt`, `1,5kg Puten Schnitzel`, `1 Kiste Pepsi Zero`, `500g Reis & Getreide::Milchreis`) and resolves the cheapest available warehouse articles **at add-to-cart time**.
  - `todo.flaschenpost_cart` — Live two-way view of your remote Flaschenpost shopping cart.
- **Button:**
  - `button.flaschenpost_sync_shopping_list_to_cart` — One-tap sync of open items into your Flaschenpost cart.

### Actions / Services
- `flaschenpost.save_shopping_list` — Create, replace, or append a named shopping list (e.g. `"Every week"`, `"Every even week"`, `"Every odd week"`). Stored lazily without pinning article IDs.
- `flaschenpost.add_shopping_lists_to_cart` — Merge $N$ shopping lists by name (supports both Flaschenpost named lists and any Home Assistant `todo.*` entity by name/ID), combine duplicate items across lists first, resolve the cheapest in-stock warehouse items right now (`€/kg` for `kg`/`g`, `€/L` for `Kiste`/`L`/`ml`, respecting optional `Category::Product` filters), calculate pack counts needed to reach minimum amounts (`1.2kg` is chosen for `1kg` when a `600g` pack has a cheaper `€/kg`), and add them to the cart.
- `flaschenpost.get_categories` — Inspect all top-level categories and subcategories available in your local Flaschenpost warehouse (`SupportsResponse.ONLY`).
- `flaschenpost.get_shopping_lists` / `flaschenpost.delete_shopping_list` — Inspect or remove named shopping lists.
- `flaschenpost.create_new_cart` — Clear all line items, discount codes, and delivery slot selections.
- `flaschenpost.search_products` — Search your local warehouse catalog (`SupportsResponse.ONLY`) with `category`, `sort_by` (`relevance`, `price`, `price_per_unit`, `price_per_kg`, `price_per_liter`), `only_crates`, and price ceilings.
- `flaschenpost.add_to_cart` — Add or update an item by `article_id` or `query` (supports unit amounts and category filters like `"500g Reis & Getreide::Milchreis"`, `"1,5kg Puten Schnitzel"`, or `"1 Kiste Pepsi Zero"`).
- `flaschenpost.buy_cart` (or `flaschenpost.place_order`) — Finalize checkout and buy the current shopping cart headlessly. Requires `confirm: true` to authorize payment and dispatch delivery. Defaults to your configured payment method (`credit_card`, `paypal`, `sepa`, or `invoice`), automatically matching your saved Credit Card (Adyen), PayPal billing agreement, or SEPA IBAN, and auto-selects the earliest open delivery window.
- `flaschenpost.select_delivery_slot` — Reserve a specific delivery window (e.g. `DIRECT` 120-min window or standard slot).
- `flaschenpost.get_favorites`, `flaschenpost.sync_shopping_list_to_cart`, `flaschenpost.reorder_last_order`.

### Category Filters (`Category::Product`)
Any shopping list item or search query can restrict product matching to a specific Flaschenpost category, subcategory, product group, or hierarchical path using `::`:
- `"500g Reis & Getreide::Milchreis"` — Selects dry pudding rice from `Kochen & Vorrat -> Reis & Getreide` (excluding ready-to-eat dairy cups in `Eier & Molkerei -> Pudding, Grieß & Milchreis`).
- `"Reis & Getreide::500g Milchreis"` — Prefix category syntax is also supported.
- `"Kochen & Vorrat::Reis & Getreide::Milchreis"` — Multi-level category paths (`::` or `>`) are also supported.

## Example: Named Weekly Shopping Lists & Merging by ISO Week Parity

```yaml
# 1. Define the three recurring lists once (lazy — resolved at cart-fill time)
- action: flaschenpost.save_shopping_list
  data:
    name: "Every week"
    items:
      - "1kg Naturjoghurt"
      - "1,5kg Puten Schnitzel"
      - "500g Heidelbeeren"
      - "500g Haferflocken"
      - "1 Kiste Pepsi Zero"
      - "1 Kiste Schwipp Schwapp Zero"
      - "500g Reis & Getreide::Milchreis"

- action: flaschenpost.save_shopping_list
  data:
    name: "Every even week"
    items:
      - "1kg Karotten"

- action: flaschenpost.save_shopping_list
  data:
    name: "Every odd week"
    items:
      - "1kg Kürbis"
```

```yaml
# 2. Automation action: merge "Every week" + even/odd week list into a fresh cart
action: flaschenpost.add_shopping_lists_to_cart
data:
  clear_cart_first: true
  mark_completed: false
  shopping_lists:
    - "Every week"
    - "{{ 'Every even week' if (now().isocalendar()[1] % 2 == 0) else 'Every odd week' }}"
```

## Automation Examples

- **[Bring! <-> Flaschenpost Bi-Directional Sync](./example/bring_sync/README.md)**: Automatically sync items from a Bring! to-do list into a Flaschenpost shopping list (with amount and unit parsing), and automatically mark them as completed in Bring! when the Flaschenpost order is placed.
- **[Automated Cart Filling](./example/automated_cart_filling/README.md)**: Automatically merge multiple shopping lists into the cart on a recurring schedule with smart sorting algorithms (cheapest price, price per kg/liter) and out-of-stock reporting.
- **[Automated Cart Ordering](./example/automated_ordering/README.md)**: Automatically select delivery slots and place paid orders with safety thresholds (), or trigger 1-tap actionable mobile approval notifications.

## Installation via HACS

1. Open **HACS** in Home Assistant -> **Integrations** -> top-right menu -> **Custom repositories**.
2. Add this repository URL with category **Integration**.
3. Install **Flaschenpost** and restart Home Assistant.
4. Go to **Settings -> Devices & Services -> Add Integration -> Flaschenpost** and sign in with your Flaschenpost email & password.
5. In the **Verify Delivery Location & Warehouse** step, check or adjust your pin on the interactive map (defaults to your Home Assistant home location or Flaschenpost profile address). The integration verifies delivery coverage and assigns your local warehouse. You can also manage shopping lists with live preview search directly in the setup wizard or anytime later via **Configure**.

## OpenAPI Specification

See [`research/openapi.yaml`](./research/openapi.yaml) and [`research/README.md`](./research/README.md) for the full extracted and live-verified API contract.
