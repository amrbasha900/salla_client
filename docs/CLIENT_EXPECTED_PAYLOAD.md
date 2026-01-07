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
