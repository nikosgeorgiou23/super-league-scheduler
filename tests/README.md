# Test coverage

Run `.venv\Scripts\python.exe -m pytest -q` after installing `.[test]`.

Tests check the strength formulas, absence marker 15, all tie breakers, alternate
Big 4 inputs, local seeded draws, replay, invalid market values, all nine round
boundary combinations (only a 13-14 rematch is forbidden; 12-15 and 11-16
are allowed by that rule), Big 4 windows across both halves, protected hosts,
home/away streak limits (including rounds 12-14 and 13-15), full
and partial mirrors accepted (including a full-model mirrored solution), removed rules, record metadata, KPI tampering, integer
scaling, overflow rejection, and analytical optimization optima at lambda 0,
0.5 and 3. Model checks force contradictory fixtures and require INFEASIBLE;
UNKNOWN is never accepted as an infeasibility proof. Partial record fixtures only
assert individual check families and are never claimed to be valid schedules.
Historical examples retain their original provenance and are rechecked rather
than trusted. The validator is also imported in a clean subprocess to verify it
does not import OR-Tools or model.py.

Monday coverage checks seven distinct matches across eight available slots,
an unused slot, duplicate Monday assignments, protected hosts on three different
days, the 0.3 Monday value, and a full-model feasible season using Monday.
Chart tests cover PNG generation, desktop opening, and CLI output ordering.
Install `.[test,plot]` to include the matplotlib-dependent checks.
