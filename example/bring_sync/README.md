# Bring! <-> Flaschenpost Bi-Directional Shopping List Sync

This example demonstrates how to configure a two-way synchronization between a **Bring!** shopping list (using Home Assistant's official Bring! integration) and **Flaschenpost**:

1. **Bring -> Flaschenpost**: When items are added to your Bring! list, an automation updates a dedicated Flaschenpost shopping list (named `"Bring"`), automatically inspecting the Bring item description for amounts and unit suffixes (e.g. `500g`, `1kg`, `1.5l`, or raw numbers like `2`).
2. **Order Placement & Auto-Consume**: When an order is placed on Flaschenpost, the bought items are automatically deleted from the Flaschenpost shopping list.
3. **Flaschenpost -> Bring**: The item consumption triggers a Home Assistant Event Entity (`event.flaschenpost_bring_item_consumed`), which automatically marks the bought items as **completed** in your Bring! to-do list.

Everything is achieved entirely via standard Home Assistant automations—**no custom Python scripts required**.

---

## Step 1: Configure the Flaschenpost Shopping List

You need to configure the `"Bring"` list to delete its items when an order is placed (`consume_on_order: true`, `consume_action: "delete"`).

You can configure this in either of two ways:

### Option A: Via the Flaschenpost Panel UI
1. Open the **Flaschenpost** sidebar panel.
2. Select or create the `"Bring"` list tab.
3. In the list options bar:
   - Check **⚡ Bei Bestellung verbrauchen (Auto-Consume)**.
   - Set **Aktion** to **Vollständig löschen**.

### Option B: Via Developer Tools -> Actions
Run this service call once in **Developer Tools** → **Actions**:

```yaml
action: flaschenpost.set_shopping_list_config
data:
  list_name: "Bring"
  consume_on_order: true
  consume_action: "delete"
```

---

## Step 2: Add the Automations

Copy the contents of [`automations.yaml`](./automations.yaml) into your Home Assistant configuration (e.g., in `/config/automations.yaml` or via **Settings → Automations & Scenes**).

Make sure to replace `todo.bring_einkaufsliste` with your actual Bring To-Do entity ID.

### Automation 1: Sync open items to Flaschenpost (with amount parsing)

In Bring!, the item name is stored in `summary` (e.g. `Bananen`, `Milchreis`), while the specification/amount is stored in `description` (e.g. `2`, `500g`, `1.5l`).

This automation parses the `description`:
- **Raw numbers or counts** (e.g., `"2"`, `"3"`, `"2x"`) are treated as unit quantities and formatted as `2x Bananen`.
- **Numbers with supported suffixes** (e.g., `"500g"`, `"1kg"`, `"1.5l"`, `"250ml"`) are prepended as `500g Milchreis` or `1.5l Hafermilch`.
- **Plain text notes or empty descriptions** simply use the item name as `Brot`.

```yaml
alias: "Bring: Sync open items to Flaschenpost"
description: "Syncs open items from the Bring to-do list into the Flaschenpost Bring shopping list, parsing amounts from description"
trigger:
  - trigger: state
    entity_id: todo.bring_einkaufsliste
    not_to:
      - unavailable
      - unknown
action:
  - action: todo.get_items
    target:
      entity_id: todo.bring_einkaufsliste
    data:
      status: needs_action
    response_variable: bring_list

  - action: flaschenpost.save_shopping_list
    data:
      name: "Bring"
      replace: true
      items: >
        {% set ns = namespace(items=[]) %}
        {% for it in bring_list['todo.bring_einkaufsliste']['items'] %}
          {% set desc = (it.description | default('', true)) | trim %}
          {% set name = it.summary | trim %}
          {% if desc %}
            {# Raw number or unit count like '2', '2x', '2 stk' -> unit count (e.g. '2x Bananen') #}
            {% if desc | regex_match('^\\d+(?:[.,]\\d+)?(?:\\s*(?:x|stk|stück))?$', ignorecase=true) %}
              {% set num = (desc | regex_findall('\\d+(?:[.,]\\d+)?'))[0] %}
              {% set line = num ~ 'x ' ~ name %}
            {# Number with supported unit suffixes (g, kg, l, ml, etc.) -> e.g. '500g Reis', '1.5l Milch' #}
            {% elif desc | regex_match('^\\d+(?:[.,]\\d+)?\\s*(?:kg|kilo|kilogramm|g|gr|gramm|l|ltr|liter|ml|milliliter|kiste|kisten|flasche|flaschen|pkg|packung|dose|dosen)$', ignorecase=true) %}
              {% set line = desc ~ ' ' ~ name %}
            {% else %}
              {% set line = name %}
            {% endif %}
          {% else %}
            {% set line = name %}
          {% endif %}
          {% set ns.items = ns.items + [line] %}
        {% endfor %}
        {{ ns.items }}
mode: restart
```

### Automation 2: Mark Bring item complete on order

```yaml
alias: "Flaschenpost: Mark Bring item complete on order"
description: "Marks bought items as completed in the Bring to-do list when an order is placed"
trigger:
  - trigger: state
    entity_id: event.flaschenpost_bring_item_consumed
    not_to:
      - unavailable
      - unknown
action:
  - action: todo.update_item
    target:
      entity_id: todo.bring_einkaufsliste
    data:
      # 'query' contains the product name stripped of counts, units, and tags (matching Bring's summary)
      item: "{{ state_attr('event.flaschenpost_bring_item_consumed', 'query') }}"
      status: completed
mode: queued
max: 50
```

---

## Alternative: Triggering on the Event Bus

If you prefer triggering directly on Home Assistant's event bus instead of the entity state, you can listen for the `flaschenpost_item_consumed` event:

```yaml
trigger:
  - trigger: event
    event_type: flaschenpost_item_consumed
    event_data:
      list_name: "Bring"
action:
  - action: todo.update_item
    target:
      entity_id: todo.bring_einkaufsliste
    data:
      item: "{{ trigger.event.data.query }}"
      status: completed
mode: queued
max: 50
```

---

## Available Event Attributes

| Field | Example | Description |
|---|---|---|
| `query` | `"Milch"` | Normalized product name (ideal for matching Bring items) |
| `summary` | `"2x Milch [€/l]"` | Raw shopping list item text |
| `quantity` | `2` | Requested quantity |
| `unit_type` | `"unit"`, `"weight_g"`, `"volume_ml"` | Unit classification |
| `article_id` | `28435` | The Flaschenpost article ID that was ordered |
| `action` | `"delete"` | Consumption action performed (`"delete"` or `"complete"`) |
| `order_id` | `"ord-12345"` | Internal Flaschenpost order ID |
| `order_number` | `"12345678"` | Human-readable Flaschenpost order number |
