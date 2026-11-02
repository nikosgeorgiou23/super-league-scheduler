# Historical slot scores

`top8_time_slots.csv` contains the eight aggregate scores previously computed
in the historical scheduling analysis. It is used only by the research chart
in this directory. The scheduler uses fixed values from `data/slots.json`;
this historical analysis does not supply its slots or weights.

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
