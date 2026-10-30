# Test coverage

Run `.venv\Scripts\python.exe -m pytest -q` after installing `.[test]`.
Pytest discovers the suite under `tests/` via `pyproject.toml`; generated
artifacts under `outputs/` are not scanned for tests.

Tests check the strength formulas, absence marker 15, all tie breakers, alternate
top-four strength rankings, local seeded draws, replay, invalid market values, all nine round
boundary combinations (only a 13-14 rematch is forbidden; 12-15 and 11-16
are allowed by that rule), unrestricted consecutive top-strength opponents, protected hosts,
home/away streak limits (including rounds 12-14 and 13-15), full
and partial mirrors accepted (including a full-model mirrored solution), removed rules, record metadata, KPI tampering, integer
scaling, overflow rejection, and analytical optimization optima at lambda 0,
0.5 and 3. Model checks force contradictory fixtures and require INFEASIBLE;
UNKNOWN is never accepted as an infeasibility proof. Partial record fixtures only
assert individual check families and are never claimed to be valid schedules.
Historical examples retain their original provenance and are rechecked rather
than trusted. The validator is also imported in a clean subprocess to verify it
does not import OR-Tools or model.py.

The top-four strength ranking is informational metadata, exported as
`top_four_by_strength`. Replay tests cover migration of the historical
`big_four` key and rejection of forged rankings. Full-model regressions fix
pairings and require three consecutive top-strength opponents (with alternating
venues), including windows crossing the half-season boundary; the resulting
complete schedules must pass the independent validator.

Monday coverage checks seven distinct matches across eight available slots,
an unused slot, duplicate Monday assignments, protected hosts on three different
days, the 0.3 Monday value, and a full-model feasible season using Monday.
Chart tests cover PNG generation, desktop opening, and CLI output ordering.
Install `.[test,plot]` to include the matplotlib-dependent checks.

ALNS tests exercise all three destroy operators (including exactly 50 freed
matches for two teams), explicit fixing of inactive as well as active choices,
temporary no-good lifetime, and real CP-SAT repairs under every mandatory rule.
Those real repair fixtures fix pairings and venues globally and exercise slot
changes; they do not exhaustively cover unrestricted fixture rearrangements or
establish a performance benefit from using eight workers.
Controlled SA tests force worse acceptance, equal acceptance, rejection and
current-only improvements without relying on stochastic solver outcomes. They
check independent best/current copies, final-best selection, reference-loss
calibration/fallback, time-geometric cooling, adaptive segment updates/floor,
unused operators, invalid candidates, UNKNOWN versus INFEASIBLE, live notes,
solver deadline caps, and a separate 240-second ALNS clock after initial search
and validation using an injected clock. JSON/CSV history and best exports are
also checked independently.
Real repair objective checks cover lambda 3 and 7. Export/budget integration
checks also cover lambda 0 and 0.5, including fractional objective scaling.
