# Asirive Cortex — Documentation

Fresh V4 documentation set. All pre-V4 docs (V1/V2/V3 plans, fix reports,
session logs, deprecated dashboards) were removed in the 2026-10 docs cleanup —
they live in git history if you need them.

## Start here

- **[architecture/V4-ECOSYSTEM.md](architecture/V4-ECOSYSTEM.md)** — the V4
  product + ecosystem source of truth: device, app, cloud infra, contracts,
  agent harness, privacy model, decision log.

- **[architecture/CORTEX-ENGINE.md](architecture/CORTEX-ENGINE.md)** — plan for
  the power-efficient LFM3-Omni inference engine (phased, measurement-gated).
- **[architecture/FLEET-OTA-AND-SECURITY.md](architecture/FLEET-OTA-AND-SECURITY.md)** —
  how updates roll out, security gaps, fleet coverage checklist.

## Reference

- [website-faq.md](website-faq.md) — product FAQ (navigation-first framing)
- [reference/YOLOE-THREE-MODES-QUICK-REF.md](reference/YOLOE-THREE-MODES-QUICK-REF.md) —
  YOLOE API quick reference (matches current `v3_core/layer1_learner`)

## Research / vendor references

- [research/LTA_DataMall_API_User_Guide.pdf](research/LTA_DataMall_API_User_Guide.pdf)
- [research/Extended_OBU_Library_SDK_Developer_Guide.pdf](research/Extended_OBU_Library_SDK_Developer_Guide.pdf)

## Conventions

- Code is the source of truth. When docs and code disagree, code wins.
- New docs must reference V4 paths only (`v3_core/` for V3 reference only, `device/`, `infra/`, `apps/`,
  `tools/`) — never `rpi5/`, `laptop/`, `shared/`, `scripts/`, `src/`.
