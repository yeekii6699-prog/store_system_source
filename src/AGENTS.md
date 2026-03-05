# SRC KNOWLEDGE BASE

## OVERVIEW
`src/` contains runtime code only: configuration, orchestration engine, external integrations, and Flet desktop UI.
Prefer child AGENTS files for domain details (`src/core/`, `src/services/`, `src/ui/`).

## STRUCTURE
```text
src/
├── main.py                  # process entry: logger + self-check + UI
├── config/                  # settings, network, logger
├── core/                    # TaskEngine, lifecycle, threading
├── services/                # Feishu/WeChat/activation/followup logic
├── ui/                      # Flet app shell and error page
├── tools/                   # operational helper scripts
└── utils/                   # data inspection helpers
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Config load/persist chain | `src/config/settings.py` | `.env` and `config.ini` merge order |
| Runtime env checks | `src/core/system.py` | DPI + environment preflight |
| Operational scripts | `src/tools/*.py` | activation and followup smoke helpers |
| API/table debug entry | `src/utils/table_inspector.py` | field discovery and sample data |
| Domain deep dives | `src/core/AGENTS.md`, `src/services/AGENTS.md`, `src/ui/AGENTS.md` | child docs are source of truth |

## CONVENTIONS (DELTA FROM ROOT)
- Keep `src/main.py` thin; avoid putting business flow into entrypoint.
- Prefer composition in services (`wechat_*` split) over monolithic classes.
- Keep module boundaries one-way: `core/services -> ui` is forbidden.

## CROSS-LAYER CONTRACTS
- Config key lifecycle: root `AGENTS.md` convention on sync targets is authoritative.
- Workflow status strings: see `src/services/AGENTS.md` (contract data, do not rename ad hoc).
- UI thread safety: see `src/ui/AGENTS.md` (no worker-thread direct control updates).
- Lock/COM lifecycle: see `src/core/AGENTS.md` (lock discipline + COM symmetry).

## ANTI-PATTERNS
- Do not instantiate duplicated Feishu/WeChat clients across unrelated call paths; reuse engine-managed instances.
- Do not update UI controls from worker threads directly; route through queue/safe callbacks.
- Do not introduce cross-layer imports from `ui` into `services` or `core`.

## QUICK CHECKS
```bash
# canonical full checks: ../AGENTS.md
python -m src.utils.table_inspector
```
