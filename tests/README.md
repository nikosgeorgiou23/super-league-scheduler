# Planned validation

Tests will cover invalid schedules and boundary cases as the implementation is added:

- Duplicate/missing team participation and pairings.
- Reversed venues and one meeting per pair per half.
- Big-team slot eligibility and protected-city home conflicts.
- Derby counts and the first two rounds.
- Three-game home/away runs, including across rounds 13 and 14.
- Rematches at round differences 2 (invalid) and 3 (valid).

Run `python -m pytest -q` after `python -m pip install -e ".[test]"`.
Boundary tests feed independent records into the validator and inspect the relevant
check category; partial records are deliberately not claimed to be valid schedules.
