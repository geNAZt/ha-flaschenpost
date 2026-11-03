/**
 * Flaschenpost Interactive Shopping List Panel & Lovelace Card
 * Custom Web Component for Home Assistant
 */

class FlaschenpostView extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._activeList = "Einkaufsliste";
    this._lists = { Einkaufsliste: [] };
    this._listNames = ["Einkaufsliste"];
    this._categories = [];
    this._cart = null;

    // Search builder state
    this._query = "";
    this._amount = 1;
    this._unit = "x";
    this._category = "";
    this._sort = "price";
    this._positiveKeywords = [];
    this._negativeKeywords = [];
    this._preview = null;
    this._isSearching = false;
    this._searchDebounceTimer = null;
    this._editingUid = null;

    // Modals
    this._showDryRunModal = false;
    this._dryRunResult = null;
    this._showBuyModal = false;
    this._buyConfirmChecked = false;
    this._buyLoading = false;
    this._actionMessage = null;
  }

  set hass(hass) {
    const firstSet = !this._hass;
    this._hass = hass;
    if (firstSet) {
      this._loadInitialData();
    }
  }

  setConfig(config) {
    this._config = config || {};
  }

  getCardSize() {
    return 6;
  }

  async _loadInitialData() {
    if (!this._hass) return;
    await Promise.all([
      this._fetchLists(),
      this._fetchCategories(),
      this._fetchCart(),
    ]);
    this.render();
  }

  async _fetchLists() {
    if (!this._hass) return;
    try {
      const resp = await this._hass.callWS({ type: "flaschenpost/get_lists" });
      if (resp && resp.lists) {
        this._lists = resp.lists;
        this._listNames = resp.names && resp.names.length > 0 ? resp.names : Object.keys(resp.lists);
        if (!this._listNames.includes(this._activeList)) {
          this._activeList = this._listNames[0] || "Einkaufsliste";
        }
      }
    } catch (err) {
      console.error("Failed to fetch shopping lists:", err);
    }
  }

  async _fetchCategories() {
    if (!this._hass) return;
    try {
      const resp = await this._hass.callWS({ type: "flaschenpost/get_categories" });
      if (resp && resp.options) {
        this._categories = resp.options;
      }
    } catch (err) {
      console.warn("Failed to fetch category options:", err);
    }
  }

  async _fetchCart() {
    if (!this._hass) return;
    try {
      const resp = await this._hass.callWS({ type: "flaschenpost/get_cart" });
      if (resp) {
        this._cart = resp;
      }
    } catch (err) {
      console.warn("Failed to fetch cart:", err);
    }
  }

  _triggerSearchDebounced() {
    if (this._searchDebounceTimer) {
      clearTimeout(this._searchDebounceTimer);
    }
    this._searchDebounceTimer = setTimeout(() => {
      this._executeSearch();
    }, 280);
  }

  _buildCurrentQueryString() {
    const rawQ = (this._query || "").trim();
    if (!rawQ) return "";

    const parts = [rawQ];
    for (const pos of this._positiveKeywords) {
      const clean = pos.trim();
      if (clean && !rawQ.toLowerCase().includes(clean.toLowerCase())) {
        parts.push(clean);
      }
    }
    for (const neg of this._negativeKeywords) {
      const clean = neg.trim().replace(/^!+/, "");
      if (clean) {
        parts.push(`!${clean}`);
      }
    }
    return parts.join(" ");
  }

  async _executeSearch() {
    const queryWithKws = this._buildCurrentQueryString();
    if (!queryWithKws || !this._hass) {
      this._preview = null;
      this._isSearching = false;
      this.render();
      return;
    }

    this._isSearching = true;
    this.render();

    try {
      let amountPrefix = null;
      if (this._unit !== "x" || (this._amount && Number(this._amount) > 1)) {
        amountPrefix = `${this._amount}${this._unit === "x" ? "x" : this._unit}`;
      }

      const resp = await this._hass.callWS({
        type: "flaschenpost/preview_search",
        query: queryWithKws,
        amount_prefix: amountPrefix,
        category: this._category || undefined,
        sort_by: this._sort === "price" ? undefined : this._sort,
        limit: 8,
      });

      this._preview = resp;
    } catch (err) {
      console.error("Preview search failed:", err);
      this._preview = null;
    } finally {
      this._isSearching = false;
      this.render();
    }
  }

  _toggleNegativeKeyword(kw) {
    const clean = kw.trim().replace(/^!+/, "");
    const idx = this._negativeKeywords.findIndex((k) => k.toLowerCase() === clean.toLowerCase());
    if (idx >= 0) {
      this._negativeKeywords.splice(idx, 1);
    } else {
      this._negativeKeywords.push(clean);
      // Remove from positive if present
      this._positiveKeywords = this._positiveKeywords.filter((k) => k.toLowerCase() !== clean.toLowerCase());
    }
    this._triggerSearchDebounced();
  }

  _togglePositiveKeyword(kw) {
    const clean = kw.trim().replace(/^!+/, "");
    const idx = this._positiveKeywords.findIndex((k) => k.toLowerCase() === clean.toLowerCase());
    if (idx >= 0) {
      this._positiveKeywords.splice(idx, 1);
    } else {
      this._positiveKeywords.push(clean);
      // Remove from negative if present
      this._negativeKeywords = this._negativeKeywords.filter((k) => k.toLowerCase() !== clean.toLowerCase());
    }
    this._triggerSearchDebounced();
  }

  _addCustomKeyword(kw, isNegative) {
    const clean = (kw || "").trim().replace(/^[!+]+/, "");
    if (!clean) return;
    if (isNegative) {
      if (!this._negativeKeywords.some((k) => k.toLowerCase() === clean.toLowerCase())) {
        this._negativeKeywords.push(clean);
        this._positiveKeywords = this._positiveKeywords.filter((k) => k.toLowerCase() !== clean.toLowerCase());
      }
    } else {
      if (!this._positiveKeywords.some((k) => k.toLowerCase() === clean.toLowerCase())) {
        this._positiveKeywords.push(clean);
        this._negativeKeywords = this._negativeKeywords.filter((k) => k.toLowerCase() !== clean.toLowerCase());
      }
    }
    this._triggerSearchDebounced();
  }

  async _addItemToList(summary) {
    if (!summary || !this._hass) return;
    try {
      if (this._editingUid) {
        await this._hass.callWS({
          type: "flaschenpost/update_item",
          list_name: this._activeList,
          uid: this._editingUid,
          summary: summary,
        });
        this._editingUid = null;
        this._showToast(`Eintrag in '${this._activeList}' aktualisiert!`);
      } else {
        await this._hass.callWS({
          type: "flaschenpost/add_item",
          list_name: this._activeList,
          summary: summary,
        });
        this._showToast(`Zu '${this._activeList}' hinzugefügt!`);
      }
      this._clearBuilder();
      await this._fetchLists();
      this.render();
    } catch (err) {
      this._showToast(`Fehler: ${err.message || err}`, true);
    }
  }

  _clearBuilder() {
    this._query = "";
    this._amount = 1;
    this._unit = "x";
    this._category = "";
    this._sort = "price";
    this._positiveKeywords = [];
    this._negativeKeywords = [];
    this._preview = null;
    this._editingUid = null;
  }

  async _toggleItemCompleted(item) {
    if (!this._hass) return;
    try {
      await this._hass.callWS({
        type: "flaschenpost/update_item",
        list_name: this._activeList,
        uid: item.uid,
        completed: !item.completed,
      });
      await this._fetchLists();
      this.render();
    } catch (err) {
      this._showToast(`Fehler: ${err.message || err}`, true);
    }
  }

  async _deleteItem(item) {
    if (!this._hass) return;
    try {
      await this._hass.callWS({
        type: "flaschenpost/delete_item",
        list_name: this._activeList,
        uids: [item.uid],
      });
      this._showToast("Eintrag gelöscht");
      await this._fetchLists();
      this.render();
    } catch (err) {
      this._showToast(`Fehler: ${err.message || err}`, true);
    }
  }

  _loadItemIntoBuilder(item) {
    this._clearBuilder();
    this._editingUid = item.uid;
    this._query = item.query || item.summary;
    this._category = item.category || "";
    this._sort = item.sort_by || "price";
    this._negativeKeywords = [...(item.negative_keywords || [])];

    if (item.unit_type === "weight_g") {
      if (item.target_amount_base >= 1000) {
        this._amount = item.target_amount_base / 1000;
        this._unit = "kg";
      } else {
        this._amount = item.target_amount_base;
        this._unit = "g";
      }
    } else if (item.unit_type === "volume_ml") {
      if (item.target_amount_base >= 1000) {
        this._amount = item.target_amount_base / 1000;
        this._unit = "L";
      } else {
        this._amount = item.target_amount_base;
        this._unit = "ml";
      }
    } else if (item.unit_type === "crate") {
      this._amount = Math.round(item.target_amount_base);
      this._unit = "Kiste";
    } else {
      this._amount = item.quantity || 1;
      this._unit = "x";
    }

    this._triggerSearchDebounced();
    this.render();
    this.shadowRoot.getElementById("search-input")?.focus();
  }

  async _createNewList() {
    const name = window.prompt("Name der neuen Einkaufsliste:", "Vorrat");
    if (!name || !name.trim()) return;
    const clean = name.trim();
    try {
      await this._hass.callWS({
        type: "flaschenpost/save_list",
        name: clean,
        items: [],
      });
      this._activeList = clean;
      await this._fetchLists();
      this.render();
      this._showToast(`Liste '${clean}' erstellt!`);
    } catch (err) {
      this._showToast(`Fehler: ${err.message || err}`, true);
    }
  }

  async _deleteCurrentList() {
    if (this._listNames.length <= 1) {
      this._showToast("Die letzte Liste kann nicht gelöscht werden.", true);
      return;
    }
    if (!window.confirm(`Möchtest du die Liste '${this._activeList}' wirklich löschen?`)) {
      return;
    }
    try {
      await this._hass.callWS({
        type: "flaschenpost/delete_list",
        name: this._activeList,
      });
      this._activeList = this._listNames.find((n) => n !== this._activeList) || "Einkaufsliste";
      await this._fetchLists();
      this.render();
      this._showToast("Liste gelöscht");
    } catch (err) {
      this._showToast(`Fehler: ${err.message || err}`, true);
    }
  }

  async _runDryRunPreview() {
    if (!this._hass) return;
    try {
      this._showToast("Berechne Warenkorb-Auflösung...");
      const resp = await this._hass.callWS({
        type: "flaschenpost/preview_lists",
        shopping_lists: [this._activeList],
      });
      this._dryRunResult = resp;
      this._showDryRunModal = true;
      this.render();
    } catch (err) {
      this._showToast(`Fehler: ${err.message || err}`, true);
    }
  }

  async _syncToCart(clearFirst = false) {
    if (!this._hass) return;
    try {
      this._showToast(clearFirst ? "Warenkorb wird ersetzt..." : "Artikel werden hinzugefügt...");
      const resp = await this._hass.callWS({
        type: "flaschenpost/sync_to_cart",
        shopping_lists: [this._activeList],
        clear_cart_first: clearFirst,
        mark_completed: false,
      });
      await this._fetchCart();
      this._showDryRunModal = false;
      this._showToast(`${resp.synced_count || 0} Artikel in Warenkorb übertragen!`);
      this.render();
    } catch (err) {
      this._showToast(`Fehler: ${err.message || err}`, true);
    }
  }

  async _executeBuyCart() {
    if (!this._buyConfirmChecked) {
      this._showToast("Bitte bestätige die Bestellung über das Kontrollkästchen.", true);
      return;
    }
    this._buyLoading = true;
    this.render();
    try {
      const resp = await this._hass.callWS({
        type: "flaschenpost/buy_cart",
        confirm: true,
      });
      this._showBuyModal = false;
      this._buyConfirmChecked = false;
      this._showToast(`Bestellung #${resp.order_number || resp.order_id} erfolgreich aufgegeben! 🎉`);
      await this._fetchCart();
    } catch (err) {
      this._showToast(`Bestellfehler: ${err.message || err}`, true);
    } finally {
      this._buyLoading = false;
      this.render();
    }
  }

  _showToast(msg, isError = false) {
    this._actionMessage = { text: msg, isError };
    this.render();
    setTimeout(() => {
      if (this._actionMessage && this._actionMessage.text === msg) {
        this._actionMessage = null;
        this.render();
      }
    }, 4000);
  }

  render() {
    const listItems = (this._lists && this._lists[this._activeList]) || [];
    const openItems = listItems.filter((it) => !it.completed);
    const completedItems = listItems.filter((it) => it.completed);

    const commonNegatives = ["zucker", "bio", "alkoholfrei", "laktose", "weizen", "gezuckert"];
    const commonPositives = ["bio", "vegan", "zero", "light", "3,5%", "1,5%"];

    const cartTotal = this._cart ? this._cart.total_eur : 0;
    const minOrder = this._cart ? this._cart.min_order_value_eur : 25.0;
    const minOrderPercent = Math.min(100, Math.round((cartTotal / (minOrder || 25.0)) * 100));

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          color: var(--primary-text-color, #212121);
          background-color: var(--primary-background-color, #fafafa);
          box-sizing: border-box;
          padding: 16px;
          min-height: 100%;
        }

        * {
          box-sizing: border-box;
        }

        .header-bar {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          background: var(--card-background-color, #ffffff);
          border-radius: 12px;
          padding: 16px 20px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.06);
          margin-bottom: 16px;
        }

        .brand-title {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 1.35rem;
          font-weight: 700;
          color: var(--primary-color, #e53935);
        }

        .cart-status-card {
          display: flex;
          align-items: center;
          gap: 16px;
          flex-wrap: wrap;
        }

        .cart-pill {
          background: var(--secondary-background-color, #f0f2f5);
          padding: 6px 14px;
          border-radius: 20px;
          font-size: 0.9rem;
          font-weight: 600;
        }

        .min-order-bar {
          width: 140px;
          height: 10px;
          background: #e0e0e0;
          border-radius: 5px;
          overflow: hidden;
          position: relative;
        }

        .min-order-fill {
          height: 100%;
          background: ${this._cart && this._cart.min_order_reached ? "#4caf50" : "#ff9800"};
          width: ${minOrderPercent}%;
          transition: width 0.3s ease;
        }

        .cart-actions {
          display: flex;
          gap: 8px;
        }

        button {
          font-family: inherit;
          font-size: 0.88rem;
          font-weight: 600;
          padding: 8px 14px;
          border-radius: 8px;
          border: none;
          cursor: pointer;
          transition: all 0.2s ease;
          display: inline-flex;
          align-items: center;
          gap: 6px;
        }

        .btn-primary {
          background: var(--primary-color, #e53935);
          color: #ffffff;
        }
        .btn-primary:hover {
          opacity: 0.9;
        }

        .btn-secondary {
          background: var(--secondary-background-color, #e0e0e0);
          color: var(--primary-text-color, #212121);
        }
        .btn-secondary:hover {
          background: #d5d5d5;
        }

        .btn-success {
          background: #4caf50;
          color: white;
        }
        .btn-success:hover {
          background: #43a047;
        }

        .btn-danger {
          background: #f44336;
          color: white;
        }

        .btn-outline {
          background: transparent;
          border: 1px solid var(--divider-color, #e0e0e0);
          color: var(--primary-text-color, #212121);
        }
        .btn-outline:hover {
          background: rgba(0,0,0,0.04);
        }

        .tabs-row {
          display: flex;
          align-items: center;
          gap: 8px;
          overflow-x: auto;
          margin-bottom: 16px;
          padding-bottom: 4px;
        }

        .tab-btn {
          background: var(--card-background-color, #ffffff);
          border: 1px solid var(--divider-color, #e0e0e0);
          color: var(--primary-text-color, #212121);
          padding: 8px 16px;
          border-radius: 20px;
          font-weight: 600;
          white-space: nowrap;
        }
        .tab-btn.active {
          background: var(--primary-color, #e53935);
          color: #ffffff;
          border-color: var(--primary-color, #e53935);
        }

        .layout-grid {
          display: grid;
          grid-template-columns: 1fr;
          gap: 16px;
        }

        @media (min-width: 900px) {
          .layout-grid {
            grid-template-columns: 420px 1fr;
          }
        }

        .panel-card {
          background: var(--card-background-color, #ffffff);
          border-radius: 12px;
          padding: 16px 20px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }

        .card-title {
          font-size: 1.1rem;
          font-weight: 700;
          margin-bottom: 14px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .form-group {
          margin-bottom: 12px;
        }

        label {
          display: block;
          font-size: 0.82rem;
          font-weight: 600;
          color: var(--secondary-text-color, #757575);
          margin-bottom: 5px;
        }

        input[type="text"], input[type="number"], select {
          width: 100%;
          padding: 9px 12px;
          border-radius: 8px;
          border: 1px solid var(--divider-color, #cccccc);
          background: var(--primary-background-color, #ffffff);
          color: var(--primary-text-color, #212121);
          font-size: 0.95rem;
          outline: none;
        }
        input:focus, select:focus {
          border-color: var(--primary-color, #e53935);
        }

        .amount-unit-row {
          display: grid;
          grid-template-columns: 110px 1fr;
          gap: 8px;
        }

        .chips-container {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 6px;
        }

        .chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 4px 10px;
          border-radius: 16px;
          font-size: 0.82rem;
          font-weight: 600;
          cursor: pointer;
          user-select: none;
          transition: all 0.15s ease;
        }

        .chip-neg-avail {
          background: #ffebee;
          color: #c62828;
          border: 1px dashed #ef9a9a;
        }
        .chip-neg-avail:hover {
          background: #ffcdd2;
        }

        .chip-neg-active {
          background: #d32f2f;
          color: #ffffff;
          border: 1px solid #b71c1c;
        }

        .chip-pos-avail {
          background: #e8f5e9;
          color: #2e7d32;
          border: 1px dashed #a5d6a7;
        }
        .chip-pos-avail:hover {
          background: #c8e6c9;
        }

        .chip-pos-active {
          background: #388e3c;
          color: #ffffff;
          border: 1px solid #1b5e20;
        }

        .chip-close {
          font-size: 1.05rem;
          line-height: 1;
          margin-left: 2px;
        }

        .custom-kw-adder {
          display: flex;
          gap: 6px;
          margin-top: 8px;
        }

        .winner-banner {
          background: #fff8e1;
          border: 2px solid #ffe082;
          border-radius: 10px;
          padding: 12px 16px;
          margin: 14px 0;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .winner-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          background: #ffa000;
          color: #ffffff;
          font-size: 0.75rem;
          font-weight: 800;
          padding: 2px 8px;
          border-radius: 12px;
          width: fit-content;
          text-transform: uppercase;
        }

        .candidate-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.85rem;
          margin-top: 10px;
        }

        .candidate-table th {
          background: var(--secondary-background-color, #f5f5f5);
          text-align: left;
          padding: 8px 10px;
          font-weight: 700;
          color: var(--secondary-text-color, #616161);
        }

        .candidate-table td {
          padding: 8px 10px;
          border-top: 1px solid var(--divider-color, #eeeeee);
          vertical-align: middle;
        }

        .badge-winner {
          background: #4caf50;
          color: white;
          font-weight: 700;
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 0.75rem;
        }
        .badge-instock {
          background: #e3f2fd;
          color: #1565c0;
          font-weight: 600;
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 0.75rem;
        }
        .badge-nostock {
          background: #ffebee;
          color: #c62828;
          font-weight: 600;
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 0.75rem;
        }

        .list-items-table {
          width: 100%;
          border-collapse: collapse;
          margin-top: 8px;
        }

        .list-items-table td {
          padding: 10px 8px;
          border-bottom: 1px solid var(--divider-color, #f0f0f0);
          vertical-align: middle;
        }

        .item-text {
          font-size: 0.95rem;
          font-weight: 600;
        }
        .item-text.completed {
          text-decoration: line-through;
          color: var(--secondary-text-color, #9e9e9e);
        }

        .item-note {
          font-size: 0.8rem;
          color: var(--secondary-text-color, #757575);
          margin-top: 2px;
        }

        .modal-overlay {
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 20px;
        }

        .modal-box {
          background: var(--card-background-color, #ffffff);
          border-radius: 12px;
          max-width: 720px;
          width: 100%;
          max-height: 85vh;
          overflow-y: auto;
          padding: 20px 24px;
          box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }

        .toast {
          position: fixed;
          bottom: 24px;
          right: 24px;
          padding: 12px 20px;
          border-radius: 8px;
          color: white;
          font-weight: 600;
          box-shadow: 0 4px 12px rgba(0,0,0,0.2);
          z-index: 1200;
          animation: slideUp 0.25s ease;
        }
        .toast.success { background: #323232; }
        .toast.error { background: #d32f2f; }

        @keyframes slideUp {
          from { transform: translateY(20px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
      </style>

      <!-- Toast message -->
      ${
        this._actionMessage
          ? `<div class="toast ${this._actionMessage.isError ? "error" : "success"}">${this._actionMessage.text}</div>`
          : ""
      }

      <!-- Top Header & Cart summary -->
      <div class="header-bar">
        <div class="brand-title">
          <span>🛒</span> Flaschenpost Einkaufslisten
        </div>
        <div class="cart-status-card">
          <div class="cart-pill">
            Warenkorb: <strong>${(cartTotal || 0).toFixed(2)} €</strong>
          </div>
          <div title="Mindestbestellwert: ${minOrder.toFixed(2)} €">
            <div style="font-size:0.75rem; color:var(--secondary-text-color,#666); margin-bottom:2px;">
              ${this._cart && this._cart.min_order_reached ? "Mindestbestellwert erreicht! ✓" : `Noch ${(this._cart ? this._cart.remaining_to_min_eur : 0).toFixed(2)} €`}
            </div>
            <div class="min-order-bar">
              <div class="min-order-fill"></div>
            </div>
          </div>
          <div class="cart-actions">
            <button class="btn-outline" id="btn-dryrun-cart">🔍 Live Vorschau</button>
            <button class="btn-primary" id="btn-sync-cart">📥 In Warenkorb</button>
            <button class="btn-success" id="btn-buy-modal">⚡ Bestellen</button>
          </div>
        </div>
      </div>

      <!-- Named Lists Tabs -->
      <div class="tabs-row">
        ${this._listNames
          .map((lname) => {
            const count = (this._lists[lname] || []).filter((i) => !i.completed).length;
            const activeCls = lname === this._activeList ? "active" : "";
            return `
              <button class="tab-btn ${activeCls}" data-list-name="${lname}">
                ${lname} (${count})
              </button>
            `;
          })
          .join("")}
        <button class="btn-outline" id="btn-add-list">+ Neue Liste</button>
        ${
          this._listNames.length > 1
            ? `<button class="btn-outline btn-danger" id="btn-delete-list" title="Aktive Liste löschen">🗑</button>`
            : ""
        }
      </div>

      <!-- Main Layout: Left = Builder, Right = List items & Preview -->
      <div class="layout-grid">
        <!-- Search & Interactive Builder Panel -->
        <div class="panel-card">
          <div class="card-title">
            <span>${this._editingUid ? "✏️ Eintrag bearbeiten" : "🔍 Artikel suchen & konfigurieren"}</span>
            ${
              this._editingUid
                ? `<button class="btn-outline" style="font-size:0.75rem; padding:4px 8px;" id="btn-cancel-edit">Abbrechen</button>`
                : ""
            }
          </div>

          <div class="form-group">
            <label for="search-input">Produktbegriff</label>
            <input type="text" id="search-input" placeholder="z.B. Heidelbeeren, Hafermilch, Cola..." value="${this._query || ""}" />
          </div>

          <div class="form-group amount-unit-row">
            <div>
              <label for="amount-input">Menge</label>
              <input type="number" id="amount-input" step="any" min="0.1" value="${this._amount || 1}" />
            </div>
            <div>
              <label for="unit-select">Einheit</label>
              <select id="unit-select">
                <option value="x" ${this._unit === "x" ? "selected" : ""}>x (Stück / Packung)</option>
                <option value="g" ${this._unit === "g" ? "selected" : ""}>g (Gramm)</option>
                <option value="kg" ${this._unit === "kg" ? "selected" : ""}>kg (Kilogramm)</option>
                <option value="ml" ${this._unit === "ml" ? "selected" : ""}>ml (Milliliter)</option>
                <option value="L" ${this._unit === "L" ? "selected" : ""}>L (Liter)</option>
                <option value="Kiste" ${this._unit === "Kiste" ? "selected" : ""}>Kiste(n)</option>
              </select>
            </div>
          </div>

          <div class="form-group">
            <label for="sort-select">Sortierkriterium</label>
            <select id="sort-select">
              <option value="price" ${this._sort === "price" ? "selected" : ""}>Günstigster Gesamtpreis (Standard)</option>
              <option value="price_per_kg" ${this._sort === "price_per_kg" ? "selected" : ""}>Günstigster Grundpreis (€/kg)</option>
              <option value="price_per_liter" ${this._sort === "price_per_liter" ? "selected" : ""}>Günstigster Grundpreis (€/L)</option>
              <option value="price_per_unit" ${this._sort === "price_per_unit" ? "selected" : ""}>Günstigster Stückpreis (€/Einheit)</option>
              <option value="relevance" ${this._sort === "relevance" ? "selected" : ""}>Relevanz (Flaschenpost)</option>
            </select>
          </div>

          ${
            this._categories && this._categories.length > 0
              ? `
            <div class="form-group">
              <label for="category-select">Kategorie-Filter (Optional)</label>
              <select id="category-select">
                <option value="">Alle Kategorien</option>
                ${this._categories
                  .map(
                    (cat) => `
                  <option value="${cat.value}" ${this._category === cat.value ? "selected" : ""}>${cat.label}</option>
                `
                  )
                  .join("")}
              </select>
            </div>
          `
              : ""
          }

          <!-- Negative Keywords Builder Section -->
          <div class="form-group" style="margin-top: 14px;">
            <label style="color: #c62828;">🚫 Negative Keywords (Ausschließen mit !)</label>
            <div class="chips-container">
              ${this._negativeKeywords
                .map(
                  (kw) => `
                <span class="chip chip-neg-active" data-neg-toggle="${kw}">
                  🚫 !${kw} <span class="chip-close">×</span>
                </span>
              `
                )
                .join("")}
              ${commonNegatives
                .filter((ck) => !this._negativeKeywords.some((k) => k.toLowerCase() === ck.toLowerCase()))
                .map(
                  (ck) => `
                <span class="chip chip-neg-avail" data-neg-toggle="${ck}">
                  + !${ck}
                </span>
              `
                )
                .join("")}
            </div>
          </div>

          <!-- Positive Keywords Builder Section -->
          <div class="form-group">
            <label style="color: #2e7d32;">✓ Positive Keywords (Qualifizierer)</label>
            <div class="chips-container">
              ${this._positiveKeywords
                .map(
                  (kw) => `
                <span class="chip chip-pos-active" data-pos-toggle="${kw}">
                  ✓ ${kw} <span class="chip-close">×</span>
                </span>
              `
                )
                .join("")}
              ${commonPositives
                .filter((cp) => !this._positiveKeywords.some((k) => k.toLowerCase() === cp.toLowerCase()))
                .map(
                  (cp) => `
                <span class="chip chip-pos-avail" data-pos-toggle="${cp}">
                  + ${cp}
                </span>
              `
                )
                .join("")}
            </div>
          </div>

          <!-- Custom Keyword Adder Input -->
          <div class="custom-kw-adder">
            <input type="text" id="custom-kw-input" placeholder="Eigenes Keyword (z.B. laktose, bio)..." />
            <button class="btn-secondary" id="btn-add-pos-kw" title="Als positives Keyword">+</button>
            <button class="btn-danger" id="btn-add-neg-kw" title="Als negatives Keyword (Ausschluss)">!</button>
          </div>

          <!-- Add to List Action -->
          <div style="margin-top: 18px;">
            <button class="btn-primary" style="width: 100%; justify-content: center; padding: 12px;" id="btn-save-builder">
              ${this._editingUid ? "💾 Eintrag aktualisieren" : `➕ Zu '${this._activeList}' hinzufügen`}
            </button>
          </div>
        </div>

        <!-- Right Side: Items in Active List & Live Search Candidates -->
        <div style="display: flex; flex-direction: column; gap: 16px;">
          <!-- Live Preview Search Results Card -->
          ${
            this._query && this._query.trim()
              ? `
            <div class="panel-card">
              <div class="card-title">
                <span>Warehouse Live Preview für: <em>${this._buildCurrentQueryString()}</em></span>
                ${this._isSearching ? `<span style="font-size:0.8rem; color:#888;">Suche läuft...</span>` : ""}
              </div>

              ${
                this._preview && this._preview.winner && this._preview.winner.product
                  ? `
                <div class="winner-banner">
                  <div class="winner-badge">★ Order-Time Winner</div>
                  <div style="font-weight: 700; font-size: 1.05rem;">
                    ${this._preview.winner.quantity}x ${this._preview.winner.product.name}
                    (#${this._preview.winner.article_id})
                  </div>
                  <div style="font-size: 0.88rem; color: #555;">
                    Geliefert: <strong>${this._preview.winner.delivered_amount_base || ""}</strong> für <strong>${(this._preview.winner.line_total_eur || 0).toFixed(2)} €</strong>
                    (${this._preview.winner.product.price_per_kg_eur ? `${Number(this._preview.winner.product.price_per_kg_eur).toFixed(2)} €/kg` : `${Number(this._preview.winner.product.price_eur || 0).toFixed(2)} €`})
                  </div>
                </div>
              `
                  : this._isSearching
                  ? `<div style="padding: 12px; color: #666;">Warehouse-Katalog wird durchsucht...</div>`
                  : `<div style="padding: 12px; color: #d32f2f;">Kein lieferbares Produkt passt zu diesen Suchbegriffen & Filtern.</div>`
              }

              <!-- Candidates Table -->
              ${
                this._preview && this._preview.candidates && this._preview.candidates.length > 0
                  ? `
                <div style="overflow-x: auto;">
                  <table class="candidate-table">
                    <thead>
                      <tr>
                        <th>#SKU</th>
                        <th>Produkt</th>
                        <th>Packung</th>
                        <th>Grundpreis</th>
                        <th>Bedarf -> Summe</th>
                        <th>Status</th>
                        <th>Aktionen</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${this._preview.candidates
                        .map((c) => {
                          const isWinner = this._preview.winner && this._preview.winner.article_id === c.article_id;
                          return `
                          <tr>
                            <td><code>#${c.article_id}</code></td>
                            <td>
                              <strong>${c.name}</strong><br />
                              <span style="font-size:0.75rem; color:#888;">${(c.categories || []).slice(0, 2).join(" > ")}</span>
                            </td>
                            <td>${c.description || "1x"} (${Number(c.price_eur || 0).toFixed(2)} €)</td>
                            <td><strong>${c.base_metric || "-"}</strong></td>
                            <td>${c.packs}x (${c.delivered_amount}) = <strong>${Number(c.line_total_eur || 0).toFixed(2)} €</strong></td>
                            <td>
                              ${
                                isWinner
                                  ? `<span class="badge-winner">Winner</span>`
                                  : c.is_available
                                  ? `<span class="badge-instock">Lagernd</span>`
                                  : `<span class="badge-nostock">Ausverkauft</span>`
                              }
                            </td>
                            <td>
                              <div style="display:flex; flex-direction:column; gap:4px;">
                                <button class="btn-outline btn-pin-sku" data-sku-summary="${c.pinned_summary}" style="font-size:0.75rem; padding:4px 8px;" title="Genau diese SKU pinnen">
                                  📌 SKU #${c.article_id}
                                </button>
                              </div>
                            </td>
                          </tr>
                        `;
                        })
                        .join("")}
                    </tbody>
                  </table>
                </div>
              `
                  : ""
              }
            </div>
          `
              : ""
          }

          <!-- Active Shopping List Items Card -->
          <div class="panel-card">
            <div class="card-title">
              <span>📋 ${this._activeList} (${openItems.length} offen, ${completedItems.length} erledigt)</span>
              <div style="display: flex; gap: 8px;">
                <button class="btn-outline" id="btn-sync-active-list">In Warenkorb</button>
              </div>
            </div>

            ${
              listItems.length === 0
                ? `<div style="padding: 24px; text-align: center; color: #888;">Diese Liste ist noch leer. Nutze die Suche links, um Artikel hinzuzufügen!</div>`
                : `
              <table class="list-items-table">
                <tbody>
                  ${openItems
                    .map(
                      (item) => `
                    <tr>
                      <td style="width: 32px;">
                        <input type="checkbox" class="chk-item" data-uid="${item.uid}" />
                      </td>
                      <td>
                        <div class="item-text">${item.summary}</div>
                        ${item.last_resolved_note ? `<div class="item-note">💡 ${item.last_resolved_note}</div>` : ""}
                      </td>
                      <td style="text-align: right; white-space: nowrap;">
                        <button class="btn-outline btn-edit-item" data-uid="${item.uid}" style="padding: 4px 8px; font-size: 0.8rem;">✏️</button>
                        <button class="btn-outline btn-del-item" data-uid="${item.uid}" style="padding: 4px 8px; font-size: 0.8rem; color: #d32f2f;">✕</button>
                      </td>
                    </tr>
                  `
                    )
                    .join("")}

                  ${
                    completedItems.length > 0
                      ? `
                    <tr>
                      <td colspan="3" style="padding-top: 16px; font-size: 0.8rem; font-weight: 700; color: #888; text-transform: uppercase;">
                        Erledigt (${completedItems.length})
                      </td>
                    </tr>
                    ${completedItems
                      .map(
                        (item) => `
                      <tr>
                        <td style="width: 32px;">
                          <input type="checkbox" checked class="chk-item" data-uid="${item.uid}" />
                        </td>
                        <td>
                          <div class="item-text completed">${item.summary}</div>
                        </td>
                        <td style="text-align: right; white-space: nowrap;">
                          <button class="btn-outline btn-del-item" data-uid="${item.uid}" style="padding: 4px 8px; font-size: 0.8rem; color: #d32f2f;">✕</button>
                        </td>
                      </tr>
                    `
                      )
                      .join("")}
                  `
                      : ""
                  }
                </tbody>
              </table>
            `
            }
          </div>
        </div>
      </div>

      <!-- Dry Run Preview Modal -->
      ${
        this._showDryRunModal && this._dryRunResult
          ? `
        <div class="modal-overlay" id="modal-overlay-dryrun">
          <div class="modal-box">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
              <h2 style="margin: 0; font-size: 1.25rem;">Live Resolution Vorschau (${this._dryRunResult.lists_merged ? this._dryRunResult.lists_merged.join(", ") : ""})</h2>
              <button class="btn-outline" id="btn-close-dryrun">✕</button>
            </div>

            <div style="margin-bottom: 16px; font-size: 1.05rem;">
              Geschätzter Warenwert: <strong>${(this._dryRunResult.estimated_goods_eur || 0).toFixed(2)} €</strong>
            </div>

            <div style="overflow-x: auto; max-height: 45vh;">
              <table class="candidate-table">
                <thead>
                  <tr>
                    <th>Anfrage</th>
                    <th>Gewähltes Produkt</th>
                    <th>Menge</th>
                    <th>Grundpreis</th>
                    <th>Gesamt</th>
                  </tr>
                </thead>
                <tbody>
                  ${(this._dryRunResult.resolved_items || [])
                    .map(
                      (r) => `
                    <tr>
                      <td><code>${r.requested}</code></td>
                      <td><strong>${r.name}</strong><br /><span style="font-size:0.75rem; color:#888;">#${r.article_id}</span></td>
                      <td>${r.quantity_added}x (${r.delivered_amount})</td>
                      <td>${r.price_per_kg_eur ? `${Number(r.price_per_kg_eur).toFixed(2)} €/kg` : `${Number(r.unit_price_eur || 0).toFixed(2)} €`}</td>
                      <td><strong>${Number(r.line_total_eur || 0).toFixed(2)} €</strong></td>
                    </tr>
                  `
                    )
                    .join("")}
                </tbody>
              </table>
            </div>

            ${
              this._dryRunResult.unresolved && this._dryRunResult.unresolved.length > 0
                ? `
              <div style="margin-top: 14px; padding: 10px 14px; background: #ffebee; border-radius: 8px; color: #c62828; font-size: 0.85rem;">
                <strong>Nicht auflösbar / Ausverkauft:</strong> ${this._dryRunResult.unresolved.join(", ")}
              </div>
            `
                : ""
            }

            <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
              <button class="btn-secondary" id="btn-sync-replace">Warenkorb leeren & neu füllen</button>
              <button class="btn-primary" id="btn-sync-append">Zu aktuellem Warenkorb hinzufügen</button>
            </div>
          </div>
        </div>
      `
          : ""
      }

      <!-- Buy Cart Confirmation Modal -->
      ${
        this._showBuyModal
          ? `
        <div class="modal-overlay" id="modal-overlay-buy">
          <div class="modal-box">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
              <h2 style="margin: 0; font-size: 1.25rem; color: #2e7d32;">⚡ Flaschenpost Bestellung aufgeben</h2>
              <button class="btn-outline" id="btn-close-buy">✕</button>
            </div>

            <div style="background: var(--secondary-background-color, #f9f9f9); padding: 16px; border-radius: 8px; margin-bottom: 16px;">
              <div style="font-size: 1.1rem; font-weight: 700; margin-bottom: 8px;">
                Warenkorb Gesamtsumme: ${(cartTotal || 0).toFixed(2)} €
              </div>
              <div style="font-size: 0.9rem; color: #666;">
                Enthaltene Artikel: ${this._cart && this._cart.items ? this._cart.items.length : 0}
              </div>
            </div>

            <div style="margin: 16px 0;">
              <label style="display: flex; align-items: center; gap: 8px; font-size: 0.95rem; cursor: pointer;">
                <input type="checkbox" id="chk-buy-confirm" ${this._buyConfirmChecked ? "checked" : ""} />
                <strong>Ich bestätige die kostenpflichtige Bestellung bei Flaschenpost.</strong>
              </label>
            </div>

            <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
              <button class="btn-secondary" id="btn-cancel-buy">Abbrechen</button>
              <button class="btn-success" id="btn-submit-buy" ${!this._buyConfirmChecked || this._buyLoading ? "disabled" : ""}>
                ${this._buyLoading ? "Bestellung wird gesendet..." : "Jetzt kostenpflichtig bestellen"}
              </button>
            </div>
          </div>
        </div>
      `
          : ""
      }
    `;

    this._bindEvents();
  }

  _bindEvents() {
    const root = this.shadowRoot;

    // Search input
    const searchInput = root.getElementById("search-input");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        this._query = e.target.value;
        this._triggerSearchDebounced();
      });
      searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          this._handleSaveFromBuilder();
        }
      });
    }

    // Amount input
    const amountInput = root.getElementById("amount-input");
    if (amountInput) {
      amountInput.addEventListener("input", (e) => {
        this._amount = parseFloat(e.target.value) || 1;
        this._triggerSearchDebounced();
      });
    }

    // Unit select
    const unitSelect = root.getElementById("unit-select");
    if (unitSelect) {
      unitSelect.addEventListener("change", (e) => {
        this._unit = e.target.value;
        this._triggerSearchDebounced();
      });
    }

    // Sort select
    const sortSelect = root.getElementById("sort-select");
    if (sortSelect) {
      sortSelect.addEventListener("change", (e) => {
        this._sort = e.target.value;
        this._triggerSearchDebounced();
      });
    }

    // Category select
    const catSelect = root.getElementById("category-select");
    if (catSelect) {
      catSelect.addEventListener("change", (e) => {
        this._category = e.target.value;
        this._triggerSearchDebounced();
      });
    }

    // Toggle negative keywords
    root.querySelectorAll("[data-neg-toggle]").forEach((el) => {
      el.addEventListener("click", () => {
        this._toggleNegativeKeyword(el.dataset.negToggle);
      });
    });

    // Toggle positive keywords
    root.querySelectorAll("[data-pos-toggle]").forEach((el) => {
      el.addEventListener("click", () => {
        this._togglePositiveKeyword(el.dataset.posToggle);
      });
    });

    // Custom keyword adder
    const customKwInput = root.getElementById("custom-kw-input");
    const btnAddPos = root.getElementById("btn-add-pos-kw");
    const btnAddNeg = root.getElementById("btn-add-neg-kw");

    if (btnAddPos && customKwInput) {
      btnAddPos.addEventListener("click", () => {
        this._addCustomKeyword(customKwInput.value, false);
        customKwInput.value = "";
      });
    }
    if (btnAddNeg && customKwInput) {
      btnAddNeg.addEventListener("click", () => {
        this._addCustomKeyword(customKwInput.value, true);
        customKwInput.value = "";
      });
    }
    if (customKwInput) {
      customKwInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          this._addCustomKeyword(customKwInput.value, false);
          customKwInput.value = "";
        }
      });
    }

    // Save from builder
    const btnSaveBuilder = root.getElementById("btn-save-builder");
    if (btnSaveBuilder) {
      btnSaveBuilder.addEventListener("click", () => this._handleSaveFromBuilder());
    }

    // Cancel edit
    const btnCancelEdit = root.getElementById("btn-cancel-edit");
    if (btnCancelEdit) {
      btnCancelEdit.addEventListener("click", () => {
        this._clearBuilder();
        this.render();
      });
    }

    // Tabs
    root.querySelectorAll(".tab-btn[data-list-name]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._activeList = btn.dataset.listName;
        this.render();
      });
    });

    // Add list
    const btnAddList = root.getElementById("btn-add-list");
    if (btnAddList) {
      btnAddList.addEventListener("click", () => this._createNewList());
    }

    // Delete list
    const btnDelList = root.getElementById("btn-delete-list");
    if (btnDelList) {
      btnDelList.addEventListener("click", () => this._deleteCurrentList());
    }

    // Checkbox toggle item
    root.querySelectorAll(".chk-item[data-uid]").forEach((chk) => {
      chk.addEventListener("change", () => {
        const item = (this._lists[this._activeList] || []).find((it) => it.uid === chk.dataset.uid);
        if (item) this._toggleItemCompleted(item);
      });
    });

    // Edit item
    root.querySelectorAll(".btn-edit-item[data-uid]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = (this._lists[this._activeList] || []).find((it) => it.uid === btn.dataset.uid);
        if (item) this._loadItemIntoBuilder(item);
      });
    });

    // Delete item
    root.querySelectorAll(".btn-del-item[data-uid]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = (this._lists[this._activeList] || []).find((it) => it.uid === btn.dataset.uid);
        if (item) this._deleteItem(item);
      });
    });

    // Pin SKU buttons in candidate table
    root.querySelectorAll(".btn-pin-sku[data-sku-summary]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._addItemToList(btn.dataset.skuSummary);
      });
    });

    // Top action buttons
    const btnDryRun = root.getElementById("btn-dryrun-cart");
    if (btnDryRun) {
      btnDryRun.addEventListener("click", () => this._runDryRunPreview());
    }

    const btnSyncCart = root.getElementById("btn-sync-cart");
    if (btnSyncCart) {
      btnSyncCart.addEventListener("click", () => this._syncToCart(false));
    }

    const btnSyncActive = root.getElementById("btn-sync-active-list");
    if (btnSyncActive) {
      btnSyncActive.addEventListener("click", () => this._syncToCart(false));
    }

    const btnBuyModal = root.getElementById("btn-buy-modal");
    if (btnBuyModal) {
      btnBuyModal.addEventListener("click", () => {
        this._showBuyModal = true;
        this.render();
      });
    }

    // Modals
    const btnCloseDryRun = root.getElementById("btn-close-dryrun");
    if (btnCloseDryRun) {
      btnCloseDryRun.addEventListener("click", () => {
        this._showDryRunModal = false;
        this.render();
      });
    }

    const btnSyncReplace = root.getElementById("btn-sync-replace");
    if (btnSyncReplace) {
      btnSyncReplace.addEventListener("click", () => this._syncToCart(true));
    }

    const btnSyncAppend = root.getElementById("btn-sync-append");
    if (btnSyncAppend) {
      btnSyncAppend.addEventListener("click", () => this._syncToCart(false));
    }

    const btnCloseBuy = root.getElementById("btn-close-buy");
    const btnCancelBuy = root.getElementById("btn-cancel-buy");
    if (btnCloseBuy) {
      btnCloseBuy.addEventListener("click", () => {
        this._showBuyModal = false;
        this.render();
      });
    }
    if (btnCancelBuy) {
      btnCancelBuy.addEventListener("click", () => {
        this._showBuyModal = false;
        this.render();
      });
    }

    const chkBuyConfirm = root.getElementById("chk-buy-confirm");
    if (chkBuyConfirm) {
      chkBuyConfirm.addEventListener("change", (e) => {
        this._buyConfirmChecked = e.target.checked;
        const btnSubmit = root.getElementById("btn-submit-buy");
        if (btnSubmit) {
          btnSubmit.disabled = !this._buyConfirmChecked || this._buyLoading;
        }
      });
    }

    const btnSubmitBuy = root.getElementById("btn-submit-buy");
    if (btnSubmitBuy) {
      btnSubmitBuy.addEventListener("click", () => this._executeBuyCart());
    }
  }

  _handleSaveFromBuilder() {
    let summary = "";
    if (this._preview && this._preview.lazy_summary) {
      summary = this._preview.lazy_summary;
    } else {
      const q = this._buildCurrentQueryString();
      if (!q) return;
      const amtPart = this._unit === "x" && Number(this._amount) <= 1 ? "" : `${this._amount}${this._unit === "x" ? "x" : this._unit} `;
      const catPart = this._category ? `${this._category}::` : "";
      const sortPart = this._sort && this._sort !== "price" ? ` [${this._sort}]` : "";
      summary = `${amtPart}${catPart}${q}${sortPart}`;
    }
    this._addItemToList(summary);
  }
}

customElements.define("flaschenpost-view", FlaschenpostView);

class FlaschenpostPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = document.createElement("flaschenpost-view");
    this.shadowRoot.appendChild(this._view);
  }

  set hass(hass) {
    this._view.hass = hass;
  }

  set panel(panel) {
    this._view.setConfig(panel && panel.config ? panel.config : {});
  }
}

customElements.define("flaschenpost-panel", FlaschenpostPanel);

class FlaschenpostCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = document.createElement("flaschenpost-view");
    this.shadowRoot.appendChild(this._view);
  }

  set hass(hass) {
    this._view.hass = hass;
  }

  setConfig(config) {
    this._view.setConfig(config || {});
  }

  getCardSize() {
    return 6;
  }
}

customElements.define("flaschenpost-card", FlaschenpostCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "flaschenpost-card",
  name: "Flaschenpost Shopping List Card",
  description: "Interactive Flaschenpost shopping list with live product search, keyword chips, and cart actions",
  preview: true,
});
