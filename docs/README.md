# Asirive Cortex — Documentation

Fresh V4 documentation set. All pre-V4 docs (V1/V2/V3 plans, fix reports,
session logs, deprecated dashboards) were removed in the 2026-10 docs cleanup —
they live in git history if you need them.

## Start here

- **[architecture/V4-ECOSYSTEM.md](architecture/V4-ECOSYSTEM.md)** — the V4
  product + ecosystem source of truth: device, app, cloud infra, contracts,
  agent harness, privacy model, decision log.

## Reference

- [website-faq.md](website-faq.md) — product FAQ (navigation-first framing)
- [reference/YOLOE-THREE-MODES-QUICK-REF.md](reference/YOLOE-THREE-MODES-QUICK-REF.md) —
  YOLOE API quick reference (matches current `core/layer1_learner`)

## Research / vendor references

- [research/LTA_DataMall_API_User_Guide.pdf](research/LTA_DataMall_API_User_Guide.pdf)
- [research/Extended_OBU_Library_SDK_Developer_Guide.pdf](research/Extended_OBU_Library_SDK_Developer_Guide.pdf)

## Conventions

- Code is the source of truth. When docs and code disagree, code wins.
- New docs must reference V4 paths only (`core/`, `device/`, `infra/`, `apps/`,
  `tools/`) — never `rpi5/`, `laptop/`, `shared/`, `scripts/`, `src/`.
