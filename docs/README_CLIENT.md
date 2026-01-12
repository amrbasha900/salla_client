# Salla Client (Phase 3)

This app runs on the merchant ERP server. It receives signed commands from **Salla Manager**, applies them to ERP, and exposes a manual pull helper for testing.

## Configure the Manager connection

1. Open the **Salla Manager Connection** Single DocType.
2. Fill:
   - `manager_base_url` (Manager site URL, no trailing slash)
   - `instance_id` (must match the Manager record)
   - `shared_secret` (password from Manager)
   - Optional `allowed_manager_ips` (comma separated) to lock down the receiver.
   - Feature toggles: `enable_push_receive_products`, `enable_push_receive_orders`, `enable_manual_pull`.
3. Save. Status can be set to `connected` once the handshake is verified.

## HMAC receive endpoint (Manager ➜ Client)

- URL: `/api/method/salla_client.api.receive_command`
- Method: POST, `Content-Type: application/json`
- Required headers:
  - `X-Instance-ID`, `X-Timestamp`, `X-Nonce`, `X-Signature`, `X-Idempotency-Key`
- Signature: `hex(hmac_sha256(shared_secret, f"{timestamp}.{nonce}.{raw_body}"))`
- Timestamp window: configurable in **Salla Manager Connection** (`timestamp_window_seconds`, default 300s)
- Nonce replay is blocked via `Client Nonce Log`.
- Idempotency is enforced via `Client Incoming Command.idempotency_key`.

### Responses

```json
{ "ok": true, "idempotency_key": "...", "status": "applied|skipped|failed", "errors": [] }
```

## Manual pull (Client ➜ Manager)

- URL: `/api/method/salla_client.api.request_pull_from_manager`
- Body: `{ "store_id": "...", "entity_types": ["products","orders","customers"], "since": "...", "limit": 50 }`
- The client signs the request with the same HMAC headers and forwards to Manager: `/api/method/salla_manager.api.client.request_pull`.
- Controlled by `enable_manual_pull` toggle.

## Observability DocTypes

- **Client Incoming Command**: logs every command with idempotency key, payload, status, and apply results.
- **Client Apply Result** (child): ERP doc reference + warnings/errors JSON.
- **SKU Skip Log**: tracks products/variants skipped due to missing SKU (store_id, entity_type, external_id, sku, reason).
- **Client Nonce Log**: prevents nonce replay.

## Mandatory SKU rule

- Products and variants **must** have a SKU. Missing SKU → command is **skipped**, recorded in `SKU Skip Log`, and returned as `status: "skipped"`.

## Testing checklist

1. Configure **Salla Manager Connection** with matching `instance_id` + `shared_secret`.
2. Send a signed `upsert_product` with a SKU → Item created/updated; `Client Incoming Command` shows `applied`.
3. Send the same `idempotency_key` again → response `status` stays the same, no duplicate rows.
4. Send a product without SKU → response `status: "skipped"`, entry in `SKU Skip Log`.
5. Trigger `/api/method/salla_client.api.request_pull_from_manager` → Manager queues and dispatches commands, which land in `Client Incoming Command`.

## Security notes

- All inbound requests must be HTTPS + HMAC signed.
- Timestamp/nonce replay guard defaults to 5 minutes; tune with `timestamp_window_seconds`.
- Restrict by IP using `allowed_manager_ips` where possible.
# Client Executor Integration Guide

This guide explains how the **Client Executor** integrates with the **Salla Manager** service, including connection setup, security requirements, and the command workflow.

## Manager Connection Setup
The Client Executor connects to the Manager with the following settings (typically stored in client configuration):

- **Instance ID**: ERP instance identifier shared with the Manager.
- **Shared Secret**: HMAC secret used to sign and verify requests.
- **Manager Base URL**: Root URL for Manager endpoints (used for manual pull requests).

These values are required for all authenticated communication between Manager and Client.

## HMAC Signing & Request Authentication
All Manager ➜ Client requests are signed with HMAC SHA256 and must include these headers:

- `X-Instance-ID`
- `X-Timestamp` (Unix epoch seconds)
- `X-Nonce` (unique per request)
- `X-Signature` (HMAC SHA256)
- `X-Idempotency-Key`

**Signature payload:**
```
{timestamp}.{nonce}.{raw_body}
```

**Signature:**
```
hex(hmac_sha256(shared_secret, payload))
```

### Timestamp Window
The Client should reject requests whose `X-Timestamp` is outside the allowed window configured on the Manager (e.g., a small drift allowance). This prevents replay attacks using stale timestamps.

### Nonce Replay Protection
The Client should reject any request with a reused `X-Nonce` within the replay protection window. Nonces must be unique per request and are validated alongside the timestamp.

### Idempotency Handling
The Manager provides a deterministic `X-Idempotency-Key` header and also includes `idempotency_key` in the request body. The Client must treat repeated requests with the same key as safe replays and avoid duplicating side effects.

## Feature Toggles & Manual Pull Workflow
The Manager can enable/disable command types via feature toggles (for example, to pause orders while still allowing product sync). When a toggle is disabled, the Manager will not dispatch those commands to the Client.

The Client can also initiate a manual pull from the Manager when needed:

- **Endpoint**: `POST /api/method/salla_manager.api.client.request_pull`
- **Purpose**: Request the Manager to enqueue new commands for the requested entity types.

This is useful for backfills, re-syncs, or manual recovery.

## SKU Mandatory Rule & Skip Logging
SKU is required for products and variants. If the incoming data lacks a SKU:

- The Manager skips the item as if it does not exist.
- The skip is logged in **SKU Skip Log** for audit and troubleshooting.

## Command Dispatch Overview
Manager ➜ Client commands are sent to:

```
POST /api/method/salla_executor.api.commands.receive
```

The request body includes:

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

For the expected payload fields by command type, see `docs/CLIENT_EXPECTED_PAYLOAD.md`.

## Command Acknowledgements
The Client returns acknowledgements with one of the following statuses:

- `applied`
- `skipped`
- `failed`
- `rejected`

The acknowledgement is sent in the response body from the Client Executor endpoint.
