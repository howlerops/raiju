# Langfuse implementation handoff

## Priority and authorization

Native Langfuse integration is optional and is not required for the product. The mock-only local Raiju performance qualification is complete within the limits in [HANDOFF.md](../HANDOFF.md). Retain Raiju as the current AWS-contract candidate; this handoff remains available for optional Langfuse observability and a separately scoped Gateway trial, neither of which is a prerequisite for the product.

**Current authorization: documentation and local/offline work only; provider budget $0.** No shared upgrade, production routing change, new AWS resources, paid provider call, credit purchase or repeat soak is authorized by this document. The existing disposable Raiju stack is already torn down.

The owner identified roughly $800 of potential exposure for a fully successful paid soak. This is an owner-provided estimate, not a verified invoice. The previous run exhausted finite test credits after about 12.86 hours: its retained terminal error reports no credits remaining. Preserve its failed traffic verdict, but do not treat it as evidence of a gateway memory defect. Do not repeat a paid duration-based load test to resolve a credit-budget problem.

## Existing deployment: source facts, not live inventory

Paths below are relative to the sibling `leviosa-ml-ops` repository. It was inspected read-only; no files there were changed.

The owner's UI screenshot reports **4.77.0 OSS** running. The source pins below are stale relative to that
observation; they are not the deployed version. Inventory actual images, chart, migration state and stores
before proposing an upgrade or changing shared resources.


| Source | Checked-in contract / implementation consequence |
|---|---|
| `helm/langfuse/Chart.yaml`, `Chart.lock` | App 4.3.1, upstream chart 1.5.41; wrapper chart 0.5.0. Regenerate the lock when deliberately changing the dependency; do not hand-edit only the image tag. |
| `helm/langfuse/values.yaml` | Image 4.3.1; external PostgreSQL and Redis; operator-managed ClickHouse HTTP endpoint; S3-backed storage. Do not copy its production account, ingress, storage or IAM settings into a trial. |
| Same file: migration env | `LANGFUSE_MIGRATION_V4_WRITE_MODE=events_only`, native OTEL behavior `direct`, preview opt-in true. Preserve this coherent combination; this is not a new v3-to-v4 cutover. |
| Same file: schema settings | Automatic ClickHouse migration disabled; PostgreSQL `SKIP_MIGRATIONS=false`. Upgrade planning must cover both database systems, not just the gateway pod. |
| Same file: ClickHouse settings | Bundled ClickHouse has `deploy: false`. Earlier comments saying to retain it conflict with the later retirement section; do not re-enable it based on stale comments. The migration URL from the external secret is documented as stale. |
| `helm/langfuse-clickhouse/schema-migration-job.yaml` | Migration image pinned to 4.3.1; targets the operator-managed native endpoint, unlike the stale URL described above. Rehearse the target-version schema migration explicitly. |
| `helm/langfuse-clickhouse/backup-cronjob.yaml` | Backup job exists in source; existence is not proof of a current usable backup. Verify restore on isolated storage before a shared upgrade. |
| `helm/langfuse/templates/external-secret.yaml`, `namespace.yaml`, `secret-store.yaml`, `service-account.yaml` | Several names/namespaces are hard-coded to the shared installation. A different Helm release name alone does not isolate a trial. Parameterize or replace those resources in a trial-specific chart. Never sync the shared secret into a test namespace. |
| `helm/langfuse/templates/service-monitor.yaml`, `worker-service.yaml`, `event-propagation-check-cronjob.yaml`, `prometheus-rule.yaml` | Monitoring contains deployment/version assumptions. Recheck selectors, ports and worker health behavior against the selected chart; rendered resources must monitor the actual isolated components. |

Historical README deployment commands include direct production mutations and older connection advice. They are not a trial runbook. Do not run them unchanged. Read the sibling repository's `AGENTS.md` and applicable directory instructions before implementing there.

## Track A — Langfuse observability with Raiju

This does **not** require selecting Langfuse Gateway or upgrading the shared installation merely to begin compatibility work.

Raiju already documents generic OTLP HTTP/gRPC export in [the configuration reference](config-reference.md#otel): `endpoint`, `protocol`, `service_name`, `headers`, `trace_headers`, `traces_enabled`, `sample_ratio`, `excluded_attributes` and `disable_content_logging`. Generic OTLP support does not establish native Langfuse generation semantics.

Implementation contract:

1. Start with a local collector/capture endpoint and synthetic requests against a mock provider. Keep content logging disabled; do not export authorization, virtual keys, provider keys or real customer content.
2. Inventory the actual application trace parent/span IDs and existing Langfuse instrumentation. Keep application, gateway and upstream attempts distinguishable; one application generation must not accidentally become two billable-looking generations because the gateway also emits a span.
3. Verify incoming `traceparent` continuity, distinct retry/fallback attempt spans, model/provider identity, status, timing, token usage and tool/result relationships. Do not invent account/user/session mappings or convert unknown usage into zero.
4. Against the pinned Langfuse version's documented OTLP ingestion API, prove whether existing Raiju spans appear as usable generations. If a translation is required, specify and implement the smallest explicit attribute mapping; do not claim raw OTLP is equivalent before inspecting the resulting UI/API records.
5. Only after an isolated Langfuse project/control plane is approved, send synthetic trace fixtures with **no paid inference**. Verify project isolation, retention/masking, ingestion failures and whether export failure affects inference. Keep metrics on the operational collector unless Langfuse explicitly supports them.

Acceptance: a synthetic application trace connects to its gateway attempt(s), reports correct usage/errors, contains no secrets/content under the configured policy, and is retrievable in the intended isolated project. Flush/shutdown delivery and duplicate-generation behavior must be observed, not inferred from HTTP acceptance. Do not promise durable delivery from an asynchronous exporter.

## Track B — Langfuse Gateway trial

### Compatibility decision before deployment

The evaluated gateway release is 4.79.0, not floating `latest`. The [versioned comparison](gateway-evaluation.md) retains hard gaps for required Bedrock Runtime IRSA/SigV4, native Converse/InvokeModel, native Bedrock embeddings and cross-format routes. OpenAI-compatible embeddings are now supported; Mantle through a custom OpenAI-compatible URL is possible but unverified. Do not silently replace IAM with stored provider keys or move traffic/model regions to make a test pass.

Recheck the selected exact release before implementing; current online documentation may describe newer functionality. If required contracts remain unsupported, stop the **full-replacement** track before incurring infrastructure/provider costs. An optional direct OpenAI/Anthropic pilot is a narrower scope, not a complete replacement.

### Work packages for the infrastructure repository

1. **Inventory and pin, read-only first.** Record deployed Web/Worker/chart versions and image digests with an explicit approved context/namespace. Never dump Secret values or unredacted Helm values. Select an exact compatible chart version and image digests; do not guess a compatible chart just because its version is greater than 2.2.0.
2. **Isolate.** Add a trial-specific deployment with distinct namespace, service accounts, secrets, PostgreSQL database/role, Redis queue/keyspace, ClickHouse database/cluster as required by the target migrations, and object-store paths/buckets. Shared production storage is not a default. Establish deletion ownership and infrastructure cost/TTL approval before provisioning.
3. **Rehearse schemas and restore.** Pin Web, Worker, gateway and migration images together; render/validate the chart and compare effective environment variables. Resolve duplicate env generators and stale migration endpoints in the external secret's source of truth, not an ephemeral Kubernetes patch. Run migrations only on isolated stores; prove restore before proposing any shared upgrade. Do not assume `helm rollback` reverses database migrations.
4. **Wire service authentication.** Configure the gateway-to-Web service key separately from client gateway API keys and existing Langfuse project ingestion keys. Keep the JWT private key on Web, provider-key encryption key stable, and all secrets outside Git. Test wrong key, revoked key and cross-project/organization denial. Do not reuse the user's shared provider credentials for load.
5. **Network and lifecycle.** Private gateway-to-Web connectivity, TLS at ingress, no response buffering, explicit outbound allowlists on both Web and gateway. Render request limits, proxy idle timeouts, pod memory budget/headroom and stop grace as one contract. `/ready` is configuration readiness, not a Web/provider connectivity test. Check actual dependency failures separately. Gateway operational OTEL telemetry is distinct from generation ingestion.
6. **Rotation, ingestion and rollback.** Rehearse overlapping service/JWT key rotation in the order documented for the pinned version; verify generations after rotation. Check deployment drain and long-stream truncation using mocks. Demonstrate missing/failed ingestion behavior and document the non-durable async boundary. Roll back the trial by restoring client routing and its own stores; never delete shared resources.

Deliverables: reviewed chart/lock/values/template changes in `leviosa-ml-ops`, an isolated migration/restore receipt, exact runtime images, route/SDK matrix, trace-ingestion evidence, secret-free operational runbook, explicit resource cleanup receipt, and a decision limited to the contracts actually exercised. This handoff does not claim those implementation/deployment deliverables have already been built.

## Validation and spending controls

| Stage | Workload | Authorized spend / decision |
|---|---|---|
| Now | Source review, chart render, local mocks, synthetic OTLP fixtures | $0 provider spend; no new cloud resources |
| Proposed offline pilot | Local gateway/Web with isolated stores and mock providers; synthetic 401/429, cancellation, tools, streams, rotation, dependency failure and drain | No provider calls; separately account for any approved infrastructure cost |
| Proposed live smoke | At most 20 upstream attempts across all providers, clients and tool continuations; suggested aggregate ceiling $5 | **Not authorized yet.** Owner chooses a cap, funded isolated provider project and exact cases/models before execution |
| Sustained load | Reproducible mock-provider traffic; fixed duration/concurrency and infrastructure ceiling | No paid live-provider soak by default; does not prove long-duration real-provider success |

For any approved paid smoke:

- Count **upstream attempts**, not top-level SDK operations. Disable automatic SDK/gateway retries and fallbacks unless explicitly budgeted; tool continuations and direct-provider controls each consume the same shared allowance.
- Before every dispatch reserve a conservative upper bound for input, output and any billable reasoning/cache/tool/image components using the selected model's current pricing and explicit token limits. Unknown/unbounded pricing means do not dispatch. Include Web validation/model-discovery calls and any background evaluation traffic in the plan.
- Use a single aggregate request/spend admission ledger for the entire experiment, not one allowance per agent, backend or provider. Release unused reservation only when usage is reconciled; reserve in-flight requests too. Stop when either request or money limit would be exceeded.
- Prefer a dedicated provider project/key with an enforced provider-side limit. Alerts, remaining shared credits and gateway budget estimates are **not** hard dollar caps; the evaluated Langfuse Gateway has no proven hard-spend enforcement. If neither provider enforcement nor a conservative request-bound budget is available, stay offline.
- Stop at the first credit-exhaustion or unexpected persistent failure. No automatic overnight loop, retry storm, replacement account, key rotation to evade limits, or credit top-up. Preserve the failure response and ask before any further spend.
- Record starting authorization, reserved/observed usage, model prices, upstream request counts and a post-run reconciliation. Do not report an estimated invoice as actual billing.

Minimal live cases, if approved: one small native chat and incremental stream per selected provider, one forced tool/result continuation, one synthetic native Messages judge shape, and any explicitly approved direct control. Verify usage and generation ingestion on the same requests; do not issue extra inference merely to populate dashboards. Run auth/error/fault/rotation/load cases against mocks wherever possible.

## Exit decisions

- **Observability ready:** Track A trace/generation semantics and privacy checks pass; caller routing need not change.
- **Narrow gateway pilot ready:** exact native routes and supported providers pass; unsupported traffic remains on the current gateway. This needs an explicit routing/rollback decision.
- **Full replacement ready:** every actual required provider/identity/route/caller contract passes, plus restore, privacy, rotation, operational ownership and an approved cost model. Release marketing or generic mock success is insufficient.
- **Blocked on unsupported contract or budget:** record it and stop that track. Do not buy a more expensive test to work around an architectural gap.

## Primary references and handoff prompt

- [Self-hosted gateway requirements, configuration and lifecycle](https://langfuse.com/self-hosting/configuration/ai-gateway) — live documentation; verify against the selected version.
- [Versioned 4.79.0 gateway implementation](https://github.com/langfuse/langfuse/tree/v4.79.0/ai-gateway).
- [Gateway comparison and versioned provider evidence](gateway-evaluation.md).
- [Raiju qualification and cost-exhaustion evidence summary](../HANDOFF.md).

Resume instruction: “Read this handoff and the target repository instructions. Work locally/offline first. Separate Raiju-to-Langfuse observability from Langfuse Gateway replacement. Preserve exact provider/IAM contracts, trace privacy and isolated migration/restore boundaries. No shared mutations, new cloud resources or paid API calls without explicit authorization and an aggregate enforced budget. Return the bounded compatibility decision before proposing deployment.”
