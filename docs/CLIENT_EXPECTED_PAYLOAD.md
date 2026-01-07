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
