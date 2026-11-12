# Gateway replacement evaluation

## Decision

Keep Raiju as the candidate for Totango's current AWS identity and routing contracts; do not cut production over to either candidate yet. Langfuse Gateway 4.79.0 still lacks Bedrock Runtime IRSA/SigV4 and native Converse/InvokeModel support. Prefer its upstream-maintained Rust implementation for a narrower native OpenAI/Anthropic deployment if those AWS requirements are deliberately removed and compatibility is proven. Native Langfuse integration is optional, not a product gate; the [implementation handoff](langfuse-handoff.md) remains a separate track. Do not repeat paid qualification without explicit budget approval.

This is a source/documentation comparison, not a Langfuse runtime benchmark. Neither vendor performance claims nor prior mock tests establish production readiness. Production Bifrost and shared Langfuse have not been changed.

Raiju now deliberately uses its own env variables, gateway headers, token prefixes, metric names and MCP
OAuth private claims, without legacy aliases. It is not a transparent wire-name replacement: clients, secrets,
credentials and dashboards must migrate together. Existing deployment/source names below identify the real
external system; they are not Raiju product names.

## Evidence boundary

- Raiju baseline: `a93001198b52189a6e1f1eb9f24a1c3f2fde1faa`, plus the local validation fixes recorded in HANDOFF.md.
- Totango deployment intent: adjacent `terraform-leviosa/helm/bifrost/values-common.yaml`, regional overlays, proxy templates, and `eks/iam-bifrost.tf`; not a live deployment inventory.
- Langfuse candidate: released [4.79.0](https://github.com/langfuse/langfuse/releases/tag/v4.79.0), not floating documentation or `latest` images.
- Existing Langfuse repository: `leviosa-ml-ops/helm/langfuse/Chart.yaml` pins application 4.3.1 and chart dependency 1.5.41; `values.yaml` also selects 4.3.1. The owner's UI screenshot reports **4.77.0 OSS** running. That demonstrates source/deployment drift, not a live chart, digest or database inventory.

The [launch announcement](https://langfuse.com/blog/introducing-gateway) lists only OpenAI/Anthropic. Release 4.78.0 added Bedrock; 4.79.0 adds OpenAI-compatible embeddings, OpenRouter, xAI, Vercel AI Gateway and generally available custom base URLs. Current unversioned docs list additional providers absent from the 4.79.0 registry. Provider comparisons must therefore be version-specific.

The current Raiju artifact is `sha256:841d6666a762061920744092c51f5d03f635f90c4e86d4307762a8f385d67ca5`
(credential-renewal persistence fix). Its real IRSA smoke passed 22/22 and Mantle passed 17/17.
Both unchanged processes passed actual STS lifetime expiry at 05:41:57–59Z on 2026-11-11:
default installed SDK/native Titan vectors match exactly at 1,024 dimensions, with zero restarts.
Unit, typecheck, complete Bun/http1 E2E, hardened-boot, wire-oracle and vulnerability-policy checks pass.
Real rolling, node-pinned stop-first, three-node preflight, EFS SIGKILL/NFS lease recovery, partition/rejoin,
counter preservation and ALB audit attribution pass. The full 24-hour run completed with 172,800 requests
and 1,412 valid memory samples, but **failed** its error gate: 52,217 HTTP 429 errors (30.22%).
The retained terminal provider response says “You have no credits remaining”; accepted inference stopped
increasing at about 12.86 h. Earlier individual 429 bodies are not retained. Memory's numeric bounds held
(168 MiB peak, 8.23 MiB second-half growth, zero memory-inferred restarts, same healthy gateway task at end),
but this is not a pass for 24 hours of sustained successful real-provider traffic. Evidence and original
failed verdict are retained; restoring provider quota and any repeat spend/run require owner approval.
The strict consumer SDK matrix also remains 13 passes and one fresh direct-upstream-reproduced
terminal-reason counterexample, not an all-green matrix. Production is unchanged.

The approved disposable AWS stack has been torn down after evidence collection; Terraform state is empty,
owned manual DNS/ECR and EKS resources are removed, and provider-secret deletion was requested without a
recovery window. Original source credentials and shared infrastructure were not cleanup targets.
Replenishing provider credit and repeating sustained-traffic qualification require separate owner approval.

The subsequent mock-only Linux qualification passed 60,000/60,000 gateway requests over ten minutes at
100 requests/s, with two workers capped at 2 CPU/2 GiB, authentication and logging enabled. It reached
236 simultaneous upstream streams, averaged 0.191 CPU cores and peaked at 100.67 MiB sampled cgroup memory.
Median first-token delay was 0.83–1.23 ms above direct controls. This supports bounded gateway-transport
headroom over the observed production Runtime peak minute averaging 43.95 requests/s; it does not prove
AWS hardware capacity, native Bedrock/embedding conversion cost, sub-minute burst capacity or leak freedom.
Memory half-run means increased and stream tail latency widened; neither is hidden by the zero-error verdict.
See [HANDOFF.md](../HANDOFF.md) for exact artifacts, earlier failed harness runs and expired Mantle-metrics access.


## Fit against actual Totango requirements

| Requirement | Existing gateway intent | Raiju candidate | Langfuse Gateway 4.79.0 |
|---|---|---|---|
| Bedrock Runtime using IRSA/default AWS credentials | Exact namespace/service-account trust and model allowlists | Final-image real dev smoke 22/22; actual AWS deny names isolated role; two unchanged processes pass real STS expiry with exact SDK/native vectors | API-key authentication only; no SigV4/default credential chain |
| Regional Bedrock Mantle Qwen | Separate regional bearer credential | Final-image real dev installed SDK proof 17/17, including incremental streaming and tools | No first-class Mantle connection; custom OpenAI-compatible URL is a possible, unverified path |
| Chat requests to Bedrock Claude | Gateway format conversion | Exact dev Sonnet/Luna tools and streams exercised; native Converse separately verified | Native Messages API required; no cross-format translation |
| Native Bedrock routes | Proxy permits `/bedrock/*` | Implemented | No Converse/InvokeModel gateway endpoints |
| Direct OpenAI Chat/Responses, Anthropic Messages | Provider-dependent | Existing real-provider matrix exercises these paths | Native pass-through supported; tools and cache-control fields preserved |
| Embeddings, realtime/WebSockets | Scope depends on actual caller | Final-image Titan SDK/native vectors match at 1,024 dimensions; broader realtime/provider proof remains incomplete | OpenAI-compatible embeddings now served; Bedrock embeddings explicitly excluded; no WebSockets/realtime |
| Per-key usage/model controls and hard spend enforcement | Production overlays disable native governance | Extensive governance implementation; distributed-limit semantics need acceptance | Keys can use all organization-approved models; hard spend caps remain roadmap |
| Fallbacks, guardrails, PII redaction, automatic routing | Feature/config dependent | Implemented with documented partial differences | Roadmap, not equivalent released functionality |
| Integrated Langfuse tracing and key UI | Existing application instrumentation is separate | Existing application instrumentation can remain; native gateway-to-Langfuse generation equivalence is not proven | Main advantage: native generations, usage analytics, org/user/service keys |
| Runtime/control-plane footprint | Two stateless gateway/proxy replicas; no gateway DB/PVC | Native gateway, custom patched Tov compiler/runtime; standalone JSON/JSONL persistence when enabled | Stateless Rust gateway, but key resolution and ingestion depend on compatible Langfuse Web and its stores |

Primary implementation evidence:

- [Bedrock credential encoding](https://github.com/langfuse/langfuse/blob/v4.79.0/web/src/features/ai-gateway/server/provider/bedrock.ts) explicitly reserves SigV4 access keys for later.
- [Bedrock destination validation](https://github.com/langfuse/langfuse/blob/v4.79.0/ai-gateway/src/resolution/bedrock.rs) accepts only `bedrock-runtime.<region>.amazonaws.com/{openai,anthropic}/v1` and excludes embeddings.
- [Provider registry](https://github.com/langfuse/langfuse/blob/v4.79.0/web/src/features/ai-gateway/server/provider/registry.ts) and [connection validation](https://github.com/langfuse/langfuse/blob/v4.79.0/web/src/features/ai-gateway/server/provider/connection/gatewayProviderService.ts) allow compatible custom OpenAI/Anthropic URLs but not custom Bedrock destinations or a SigV4 authentication type.
- [REST routes](https://langfuse.com/docs/gateway/features/rest-api) explicitly exclude unlisted paths, WebSockets and realtime, and state that API formats are not translated.
- [Key permissions](https://langfuse.com/docs/gateway/features/api-keys) and [roadmap](https://langfuse.com/docs/gateway/overview#roadmap).

## Existing Langfuse is not an immediate gateway dependency

[Self-hosting requirements](https://langfuse.com/self-hosting/configuration/ai-gateway#requirements) require matched Web/gateway versions at least 4.75.0 and, for chart-managed deployment, a chart release after 2.2.0. Bedrock requires a release after 4.77.0. The checked-in 1.5.41 chart is insufficient, but the observed 4.77.0 Web UI already meets the minimum Web version. Inventory the actual chart, images and migrations and reconcile source drift before deciding what needs upgrading.

The checked-in installation already selects `events_only`, so a new v3-to-v4 migration is not inherently required. It uses external PostgreSQL/Redis, operator-managed ClickHouse and S3. However, ClickHouse startup migrations are disabled, the schema migration Job is pinned to 4.3.1, and comments identify a stale migration endpoint. A version bump needs a tested migration plan, not just a gateway sidecar.

A safe Langfuse trial requires a separate non-production control plane and stores, provider credentials, service/JWT keys, and synthetic traffic. Do not point an experimental gateway at production Web or upgrade the shared observability stack merely to evaluate it.

## Operational tradeoffs to qualify

- Langfuse's conventional Rust runtime and maintained upstream product reduce bespoke compiler maintenance versus Raiju. This is a maintainability advantage, not measured reliability evidence.
- Langfuse `/ready` checks configuration, not Web/provider connectivity. Key resolution depends on Web; trace uploads are asynchronous and non-durable.
- Its documented default request cap is 16 MiB, execution limit 600 seconds, stall limit 120 seconds. Drain is capped at 300 seconds: long streams may be cut during rollout. All need comparison against real client limits.
- Default usage-only tracing avoids routine prompt/response capture, but provider error text can still carry content. Core gateway is free OSS; server-side masking, managed retention policies, project-level RBAC and audit logs are Enterprise features in the current self-hosted feature matrix.
- No equal-load latency, memory, availability or dollar-cost comparison has been run. The announcement's latency/concurrency numbers cannot be compared with Raiju's mock benchmarks.

Sources: [operations](https://langfuse.com/self-hosting/configuration/ai-gateway#operations), [versioned gateway contract](https://github.com/langfuse/langfuse/blob/v4.79.0/ai-gateway/README.md), [known limitations](https://langfuse.com/faq/all/ai-gateway-known-limitations), [self-host licensing](https://langfuse.com/pricing-self-host).

## Promotion gates

1. Preserve current provider/model, region, identity, privacy and fail-closed auth contracts; do not silently replace IRSA with stored API keys or move Mantle traffic to a different provider.
2. Exercise real caller shapes: chat, incremental streaming tools and tool results, Messages judge/cache-control, usage accounting, errors and cancellation. Native Converse and embeddings are separate cutover decisions.
3. Prove two-replica operation, rollout/drain, credential rotation, failure recovery and quota behavior in an isolated dev environment. No production DNS or service cutover during evaluation.
4. For Raiju's broader release claim, complete the staging runbook: real providers, 24-hour 512 MiB soak, actual ECS/ALB/TLS, EFS locks/crash/network lease, rolling/stop-first upgrades, cluster partition/rejoin and real identity-provider flows. Explicitly label blocked gates.
   The owner accepted leaving real Okta/Entra qualification unproven because disposable tenants are unavailable;
   this is an explicit evidence gap, not a passed identity-provider gate.
   The owner also excluded `/mcp` from Totango cutover: Raiju's process-local transport sessions fail when
   an unpinned ALB sends subsequent calls to another node. OAuth continuity is checked with node-pinned
   sessions on each node, not claimed as transparent multi-node MCP support.
5. If Langfuse closes the hard provider/authentication gaps, repeat the same workload and operational checks on a pinned release before selecting it. Fewer bespoke components is preferable only when the required behavior and security boundary are preserved.
