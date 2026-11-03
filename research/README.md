# Flaschenpost API Reverse Engineering & Live Verification

## 1. Split APK & `libapp.so` Analysis (`de.flaschenpost.app` v4.2.4)

- **Base APK (`de.flaschenpost.app.apk`) + ARM64 Split (`config.arm64_v8a.apk`):**
  - `lib/arm64-v8a/libapp.so` (`package:shop_app/...`) shows that the native Dart layer (`fp_api_client.dart`, `fp_api_manager.dart`) only calls `api.flaschen.io` for two native tasks:
    1. `registerPushToken` (`accountApiBaseUrl + '/v1/accounts/'`)
    2. `checkAppVersion` (`appApiBaseUrl + '/v1/'`)
  - All customer authentication, browsing, favorites, cart management, delivery slot selection, checkout, and order tracking run through `https://www.flaschenpost.de` inside the hybrid WebView with the Android User-Agent suffix `flaschenpost App Android 4.2.4`.

---

## 2. Live Read-Only Backend Verification Results

Every core endpoint in [`openapi.yaml`](./openapi.yaml) was verified live (`HTTP 200`):

| Endpoint | Status | Key Verified Findings |
|---|---|---|
| `POST /api/v2/account/login` | `200 OK` | Headless login succeeds directly with `captcha: ""` and returns `bearerToken`, `refreshToken`, `userId`, `webUserExternalGuid`, and auth/refresh cookies (`.AspNetCore.Cookies`, `.Fp.Session`, `fp-account-fid`, `refreshToken`). |
| `GET /api/v2/account/refresh` | `200 OK` | Returns `{ token, refreshToken }` seamlessly using session cookies. |
| `GET /api/v2/myaccount` | `200 OK` | Returns customer profile, saved addresses (with `GeoCoordinates` & `AddressReference`), `DeliveredOrders`, `PaymentInvoiceAllowed`, and `PaymentDebitLimit`. |
| `GET /webshop-cart-api/api/v4/cart` | `200 OK` | Returns active Commercetools cart, `lineItems`, `totalPrice`, `RecentlyUsedWarehouseId`, `TotalGoods`, `TotalDeposit`, and `TotalDelivery`. |
| `GET /api/v2/myaccount/order/active/0` | `200 OK` | Returns paginated active orders (`results`, `total`). |
| `GET /api/v2/myaccount/order/history/{from}/{until}/0` | `200 OK` | Returns historical orders with `OfficialStatusIconState`, `OfficialStatusMessage`, `OfficialStatusETAFrom`/`Until`, `SelectedDeliveryFrom`/`Until`, `TotalDeposit`, and full `lineItems`. |
| `GET /webshop-slots-api/api/v3/Slot/{cartId}/1` | `200 OK` | Returns `slots`, `days`, `shopState`, `request_id`, `expiry`, and `isBorderRegion`. |
| `POST /ds-recommendation-api/api/v2/recommendations/my_products/{guid}/{session}/{wh}` | `200 OK` | Returns personal favorite / regular `articleId`s (199 items verified on account). |
| `GET /elastic-query-portal/{warehouseId}/v2/search` | `200 OK` | Returns warehouse-scoped Commercetools product search results. |
| `GET /php-product-api/v1/products/prv/warehouse/{wh}` | `200 OK` | Hydrates full product titles, prices, images, and unit prices by `article_ids`. |
