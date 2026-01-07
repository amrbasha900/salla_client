# Client Expected Payloads

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
- `raw`
