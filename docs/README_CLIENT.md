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
