# Planned validation

Tests will cover invalid schedules and boundary cases as the implementation is added:

- Duplicate/missing team participation and pairings.
- Reversed venues and one meeting per pair per half.
- Big-team slot eligibility and protected-city home conflicts.
- Derby counts and the first two rounds.
- Three-game home/away runs, including across rounds 13 and 14.
- Rematches at round differences 2 (invalid) and 3 (valid).

No automated tests or solver are implemented in this initial scaffold.
