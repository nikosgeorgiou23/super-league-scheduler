# Historical slot scores

`historical_slot_scores.csv` is the single source of the eight aggregate scores
previously computed in the historical scheduling analysis. It was moved intact
from `charts/top8_time_slots.csv`; the chart now reads this file as well.

- Seasons: 2023–24, 2024–25, 2025–26, regular-season rounds 1–25 only.
- Analysis sample: 376 matches with both a recorded result and a known kickoff,
  on Monday, Saturday or Sunday. The 2025–26 source was incomplete.
- Aggregation: nonoverlapping two-hour bins, 14:00–24:00, half-open intervals.
- Score: mean of the two teams' combined, fixed repository strengths. Historical
  teams outside the current fourteen used the minimum repository strength.
- Selection: the eight highest means among bins with at least fifteen matches.
- The raw matches and original analysis scripts were deleted at the user's
  request. These aggregates were recovered from the previously recorded analysis;
  this change does not claim a new historical-data collection or recalculation.

Sources used in that analysis:

- https://openfootball.github.io/europe/greece_2023-24_gr1.json
- https://openfootball.github.io/europe/greece_2024-25_gr1.json
- https://openfootball.github.io/europe/greece_2025-26_gr1.json

The CSV retains full stored score precision and observation counts. Updating
these aggregate scores changes the computed sigmoid weights at input loading.
Weights are **historical scheduling-based proxies**, not television audience
measurements. The current loader fails explicitly on missing scores, zero
observations, invalid mappings or sigmoid saturation; it has no legacy fallback.

Model windows remain as defined in `slots.json`. `historical_slot` explicitly
maps each model slot to its containing historical two-hour bin. S4 and S5 both
use Sunday 16:00–18:00. Sunday 14:00–16:00 is not a model slot but remains part
of the available eight-score catalog when computing the sigmoid midpoint.
