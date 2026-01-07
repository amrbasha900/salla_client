# Phase 2 RPC Contract (Manager ↔ Client Executor)

Phase 2 splits responsibilities:

- **Salla Manager**: only component that talks to Salla (tokens, APIs, webhooks).
- **Client Executor**: receives signed commands from Manager and applies ERP document logic.

This document defines the command protocol, HMAC signing, idempotency, and SKU rules.

## Transport
- HTTPS JSON POST
- `Content-Type: application/json`
- Manager ➜ Client (command dispatch)
- Client ➜ Manager (manual pull request)

## Mandatory SKU Rule
- **SKU is mandatory for products and variants.**
- If a product or variant has no SKU, it is **skipped** as if it does not exist.
- Manager enforces this rule on inbound payloads and records entries in **SKU Skip Log**.

## HMAC Signing
All requests must include the following headers:

- `X-Instance-ID`: ERP Instance ID
- `X-Timestamp`: Unix epoch seconds
- `X-Nonce`: unique nonce per request
- `X-Signature`: HMAC SHA256 signature
- `X-Idempotency-Key`: unique idempotency key

Signature payload:

```
{timestamp}.{nonce}.{raw_body}
```

Signature:

```
hex(hmac_sha256(shared_secret, payload))
```

## Manager ➜ Client: Command Dispatch

**Endpoint** (client executor):
```
POST /api/method/salla_executor.api.commands.receive
```

**Request Body**
```json
{
  "command_id": "SM-COMMAND-00001",
  "command_type": "upsert_product",
  "entity_type": "product",
  "store_account": "SM-STORE-00001",
  "customer_account": "CUST-0001",
  "erp_instance": "ERP-INSTANCE-0001",
  "idempotency_key": "<sha256>",
  "payload": { /* normalized entity data */ }
}
```

**Expected Response**
```json
{
  "ack_status": "applied",
  "ack_payload": {
    "erp_doc": "ITEM-0001",
    "message": "Created"
  }
}
```

`ack_status` values:
- `applied`
- `skipped`
- `failed`
- `rejected`

### Command Types
- `upsert_product`
- `upsert_variant`
- `upsert_customer`
- `upsert_order`
- `upsert_category`
- `upsert_brand`
- `upsert_order_status`

### Normalized Payloads (baseline)
Payloads include the raw Salla payload under `raw` plus normalized keys:

- **Product**: `external_id`, `name`, `sku`, `status`, `price`, `currency`, `description`, `url`, `brand_id`, `category_ids`, `images`, `raw`
- **Variant**: `external_id`, `product_id`, `name`, `sku`, `status`, `price`, `options`, `raw`
- **Customer**: `external_id`, `name`, `email`, `phone`, `status`, `group_id`, `addresses`, `raw`
- **Order**: `external_id`, `status`, `created_at`, `currency`, `total`, `shipping`, `customer`, `items`, `raw`

## Client ➜ Manager: Manual Pull Request

**Endpoint** (manager):
```
POST /api/method/salla_manager.api.client.request_pull
```

**Request Body**
```json
{
  "store_id": "<salla_store_id>",
  "entity_types": ["products", "orders", "customers"],
  "since": "2024-01-01T00:00:00Z",
  "limit": 50
}
```

**Response**
```json
{
  "ok": true,
  "queued": {"products": 12, "orders": 3, "customers": 5},
  "skipped_missing_sku": 4
}
```

## Retry & Idempotency
- Manager assigns a unique `idempotency_key` per command (deterministic SHA256 hash).
- Retries are exponential backoff using Manager settings:
  - `retry_max_attempts`
  - `retry_backoff_seconds`
- When the max attempts are exceeded, commands are marked `dead`.

## Observability DocTypes
- **Salla Incoming Log**: inbound payloads (webhooks/manual pull)
- **SKU Skip Log**: records missing SKU skips
- **Outbound Client Command**: queued commands
- **Command Delivery Attempt**: request/response attempts
- **Command ACK Log**: acknowledgements from client executor
