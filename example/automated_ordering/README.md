# Automated Cart Ordering with Flaschenpost

This guide demonstrates how to configure Home Assistant automations to place orders automatically or semi-automatically using the `flaschenpost.place_order` service.

---

## Safety Requirements

To prevent unintended orders, `flaschenpost.place_order` strictly requires:
- `confirm: true` in the service call parameters. Calls without `confirm: true` will be rejected by Home Assistant.
- Saved payment method configured in the integration options (or specified explicitly as `payment_method: "CreditCard"` or `"SepaDirectDebit"`).
- Cart total meeting your warehouse's minimum order value (usually 25.00 € or 29.00 €).

---

## Service Parameters

```yaml
action: flaschenpost.place_order
data:
  confirm: true                       # Required safety flag
  payment_method: "CreditCard"        # Optional: CreditCard, SepaDirectDebit, PayPal
  stored_payment_id: "token-string"   # Optional: saved payment method ID
  slot_type: "Standard"               # Optional delivery slot type
  slot_from: "2026-11-05T18:00:00Z"   # Optional delivery slot start
```

---

## Recommended Automation Patterns

See [`automations.yaml`](./automations.yaml) for full YAML implementations:

### Pattern 1: Fully Automated Order Placement
Ideal for weekly recurring orders:
1. **Trigger**: Time trigger (e.g. Thursday evening at 20:00).
2. **Conditions**:
   - `sensor.flaschenpost_cart_total` is above minimum order value.
   - `sensor.flaschenpost_order_status` is `idle` (no active delivery in progress).
3. **Actions**:
   - Select delivery slot using `flaschenpost.select_delivery_slot`.
   - Place order using `flaschenpost.place_order`.
   - Send mobile notification with order number and tracking link.

### Pattern 2: Interactive 1-Tap Notification (Semi-Automated)
Ideal when you want full control before paying:
1. Automation triggers when cart reaches the free shipping threshold (`above: 29.0`).
2. Sends an actionable notification to your phone with buttons: **"✅ Jetzt bestellen"** and **"Später"**.
3. When you tap **"Jetzt bestellen"**, Home Assistant executes the `place_order` action and sends a confirmation.
