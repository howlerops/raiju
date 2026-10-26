# Behaviour changes in wave 30

Wave 30 (L210 and L211) fixed the sixth production re-audit (docs/audits/production-reaudit-6-2026-10-26.md) and added a staging validation kit.

- **L210**: request bodies over 64 KB are freed when they end (a leak since wave 26 kept every one resident; `make soak-bodies` and the CI soak job now fail on RSS growth); one tenant alone may fill `server.max_buffered_body_mb` again, and a tenant's first body may use the reserve; small requests in flight no longer block a lone big body; under contention a declared body that falls behind its pace (more than 10 s left at its rate) loses its reservation to other tenants and can then be refused part way.
- **L211**: no gateway behaviour change. New staging validation kit (docs/staging-validation.md, tests/staging, a manual staging workflow, deploy/terraform/examples/staging); the aws-ecs module gains `efs_enabled` so an EFS file system created in the same apply plans cleanly.
