# Salla Client

Salla Client is the ERP-side application used to integrate a merchant site on **Salla** with **Reflection** as the Integration Manager.

In this architecture:
- **Reflection (Integration Manager)** handles orchestration and sends integration commands.
- **Salla Client** runs on your ERP site and receives/syncs data (products, orders, customers, inventory, and related entities).

---

## What this app does

- Connects your ERP site to the Integration Manager.
- Receives signed commands from Reflection/Manager and applies them in ERP.
- Supports secure communication using instance credentials and shared secrets.
- Logs incoming commands and processing results for troubleshooting.

---

## Install on your site

Install this app on your Frappe/ERPNext bench:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch master
bench install-app salla_client
```

After installation:
1. Run migrations if needed:
   ```bash
   bench --site your-site-name migrate
   ```
2. Open your ERP site and configure the connection settings in **Salla Manager Connection**.

---

## Get the required credentials (User, API Key, Secret)

To connect your site with Reflection/Manager, you typically need:

- **User**: the integration user on your ERP site.
- **API Key**: generated for that user.
- **API Secret**: generated with the API key.
- **Instance ID**: unique ID for this ERP client instance.
- **Shared Secret**: HMAC secret shared between Manager and Client.

### How to create/retrieve User API credentials in ERPNext/Frappe

1. In your ERP site, go to **User** and open the integration user (or create one dedicated for integrations).
2. In the user form, generate **API Key** and **API Secret**.
3. Copy and store these values securely (the secret is usually shown only once).
4. Share the required values with Reflection/Manager configuration.

> Recommended: use a dedicated user with the minimum required permissions for security.

---

## Configure Salla Manager Connection

In **Salla Manager Connection**, set:

- `manager_base_url`: Reflection/Manager base URL (no trailing slash)
- `instance_id`: must match the instance registered in Manager
- `shared_secret`: shared signing secret from Manager
- Optional `allowed_manager_ips`: comma-separated IP allowlist
- Optional feature toggles (enable/disable command flows)

Save and validate connectivity.

---

## Security and signing

Salla Client validates signed incoming requests using HMAC headers such as:

- `X-Instance-ID`
- `X-Timestamp`
- `X-Nonce`
- `X-Signature`
- `X-Idempotency-Key`

This protects against tampering and replay attacks.

---

## Contributing

This app uses `pre-commit` for formatting and linting:

```bash
cd apps/salla_client
pre-commit install
```

Configured tools include:
- ruff
- eslint
- prettier
- pyupgrade

---

## License

MIT
