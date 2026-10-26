# Behaviour changes in wave 29

Wave 29 (L208 and L209) fixed the findings of the fifth production re-audit (docs/audits/production-reaudit-5-2026-10-26.md).

- **L209**: an update that keeps a record's stored name no longer gets 409 when another record shares that name from before wave 28; a PUT on a virtual key, team or customer without `name` keeps the stored name (a key's name was wiped and a team or customer got 400); a config with duplicate names logs a start-up warning and posts a "Duplicate names" notice.
- **L208**: `server.max_buffered_body_mb` is a hard limit on request-body bytes in hand again (the L205 credential share now only decides who is refused first); `server.credential_body_mb` counts per tenant (customer, else team, else key), so give a customer's keys a customer_id or team; new `server.body_reserve_mb` (default a quarter of the cap) keeps room for tenants holding nothing, so a single tenant's further bodies beside its first fill at most cap minus the reserve; a body that declares its length over 64 KB reserves the whole length at admission, so excess bodies get 503 before sending and a slow declared upload holds its full length.
