# 0004. Migrate one system at a time, with a rollback switch

Status: accepted (plan default, 2026-11-03).

**Decision.** Systems move in the order of Phase 6 (`echo` first, `director_chat` last). Each function keeps
`AI_ENGINE=legacy|graph` until Phase 8. Old and new code live side by side; there is no big-bang switch.

**Consequences.** A system switches only when its parity fixtures (`tests/parity/`) are green on `graph` and
`scripts/eval_staging.py` is no worse. The switch is reversible by an environment variable. Duplicate code lives
for the length of the migration.
