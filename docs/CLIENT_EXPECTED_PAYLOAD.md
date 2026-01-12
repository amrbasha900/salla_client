# Expected Payloads from Manager ➜ Client

Normalized payloads are forwarded by Salla Manager. The client does **no** Salla API calls; it trusts these fields to apply ERP changes.

## Common envelope

```json
{
  "command_id": "SM-COMMAND-0001",
  "command_type": "upsert_product|upsert_variant|upsert_customer|upsert_order",
  "entity_type": "product|variant|customer|order",
  "store_id": "STORE-001",
  "store_account": "SM-STORE-001",
  "idempotency_key": "<sha256>",
  "payload": { /* entity payload below */ }
}
```

Headers must carry `X-Instance-ID`, `X-Timestamp`, `X-Nonce`, `X-Signature`, `X-Idempotency-Key`.

## Product (`upsert_product`)

- `external_id` (string) – required
- `sku` (string) – **mandatory**, otherwise skipped
- `name`
- `description`
- `status` (e.g., active|inactive|hidden|draft|deleted)
- `price` (number)
- `uom` (default `Nos`)
- `is_stock_item` (bool, default true)
- `item_group` (defaults to "All Item Groups")
- `brand_id`, `category_ids`, `images`, `url`, `warehouse`, `barcode`

## Variant (`upsert_variant`)

- `external_id` (string) – required
- `product_id` (template external_id) – required
- `sku` (string) – **mandatory**, otherwise skipped
- `name`
- `status`
- `uom`
- `options` (dict/list stored on the item if the custom field exists)
- `warehouse`, `barcode`

## Customer (`upsert_customer`)

- `external_id` (string) – required
- `name`
- `email`
- `phone`
- `status`
- `customer_type` (default `Individual`)
- `group_id` / `customer_group` (default `All Customer Groups`)
- `territory` (default `All Territories`)
- `addresses`: list of `{ address_line1/street, address_line2/block, city, state, country, postal_code }`

## Order (`upsert_order`)

- `external_id` (string) – required
- `created_at` (ISO string) – default today
- `currency`
- `company` (optional; defaults to system default)
- `status`
- `raw` (stored if the field exists)
- `customer` (customer payload as above) – required
- `items`: list of
  - `external_id` (Item external_id) or `sku` (fallback)
  - `name`
  - `quantity` / `qty`
  - `price` / `rate`

Order items without a SKU are skipped with a warning; if no valid items remain, the order is marked failed.
# Client Expected Payloads

This document lists the **normalized payload fields** that the Client Executor should expect for each command type. These fields are aligned with `docs/CONTRACT.md` and always include the original Salla payload under `raw`.

## General Envelope
All commands include the following envelope keys:

- `command_id`
- `command_type`
- `entity_type`
- `store_account`
- `customer_account`
- `erp_instance`
- `idempotency_key`
- `payload`

## Command Types & Payload Fields

### upsert_product
**Entity type:** `product`

Expected payload fields:
- `external_id`
- `name`
- `sku`
This document describes the required fields for the client executor handlers in
`salla_client/services/handlers/`.

## Common Requirements
- `external_id` is required for idempotent create/update mapping.
- `raw` should include the original Salla payload when available.

## Product (`upsert_product`)
**Required fields**
- `external_id`
- `name`
- `sku` (mandatory; if missing, the product is skipped and logged)

**Optional fields**
- `status`
- `price`
- `currency`
- `description`
- `url`
- `brand_id`
- `category_ids`
- `images`
- `raw`

### upsert_variant
**Entity type:** `variant`

Expected payload fields:
- `external_id`
- `product_id`
- `name`
- `sku`
- `status`
- `price`
- `options`
- `raw`

### upsert_customer
**Entity type:** `customer`

Expected payload fields:
- `external_id`
- `name`
- `item_group`

## Variant (`upsert_variant`)
**Required fields**
- `external_id`
- `product_id` (external ID of the parent product)
- `name`
- `sku` (mandatory; if missing, the variant is skipped and logged)

**Optional fields**
- `status`
- `price`
- `options`

## Customer (`upsert_customer`)
**Required fields**
- `external_id`
- `name`

**Optional fields**
- `email`
- `phone`
- `status`
- `group_id`
- `addresses`
- `raw`

### upsert_order
**Entity type:** `order`

Expected payload fields:
- `external_id`
- `territory`
- `customer_type`

## Order (`upsert_order`)
**Required fields**
- `external_id`
- `customer` (object with at least `external_id` or sufficient info to create)
- `items` (array)

**Item required fields**
- `sku` (or `external_id` that maps to an ERP Item)
- `quantity`
- `price`

**Optional fields**
- `status`
- `created_at`
- `currency`
- `total`
- `shipping`
- `customer`
- `items`
- `raw`

### upsert_category
**Entity type:** `category`

Expected payload fields:
- `external_id`
- `name`
- `status`
- `parent_id`
- `url`
- `image`
- `raw`

### upsert_brand
**Entity type:** `brand`

Expected payload fields:
- `external_id`
- `name`
- `status`
- `logo`
- `url`
- `raw`

### upsert_order_status
**Entity type:** `order_status`

Expected payload fields:
- `external_id`
- `status`
- `updated_at`
- `raw`
