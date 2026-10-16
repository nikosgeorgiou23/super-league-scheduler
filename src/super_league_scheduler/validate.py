"""Independent validation of exported records, without importing the model."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from .data import load_inputs, derby_kind

CHECKS = ('structure', 'participation', 'pairings', 'venues', 'slots',
          'geography', 'derbies', 'derby_slots', 'saturday_big', 'streaks', 'rematches', 'metadata')


def validate_schedule(matches, teams, slots, rules):
    errors = {key: [] for key in CHECKS}
    def fail(key, message):
        errors[key].append(message)
    team = {t['id']: t for t in teams}
    slot = {s['id']: s for s in slots}
    rounds, pairs, appearances = defaultdict(list), defaultdict(list), defaultdict(list)
    if not isinstance(matches, list):
        matches = []
        fail('structure', 'Schedule must be a list')
    if len(matches) != 182:
        fail('structure', f'Expected 182 matches, got {len(matches)}')
    for index, m in enumerate(matches):
        if not isinstance(m, dict):
            fail('structure', f'Record {index}: expected object')
            continue
        r, h, a, s = (m.get(k) for k in ('round', 'home', 'away', 'slot'))
        if (type(r) is not int or r not in range(1, 27) or
                not isinstance(h, str) or not isinstance(a, str) or
                h not in team or a not in team or h == a or
                not isinstance(s, str) or s not in slot):
            fail('structure', f'Record {index}: invalid round, teams or slot')
            continue
        rounds[r].append(m)
        pairs[tuple(sorted((h, a)))].append(m)
        appearances[h, r].append(True)
        appearances[a, r].append(False)
        expected = {k: slot[s][k] for k in ('day', 'start_earliest', 'start_latest')}
        expected.update(home_name=team[h]['name'], away_name=team[a]['name'],
                        venue=h, derby=derby_kind(team[h], team[a]))
        for key, value in expected.items():
            if key not in m or m[key] != value:
                fail('metadata', f'Record {index}: incorrect {key}')
        if 'big' in (team[h]['category'], team[a]['category']) and s not in rules['big_team_allowed_slots']:
            fail('slots', f'Round {r}: big team in {s}')
    for r in range(1, 27):
        ms = rounds[r]
        if len(ms) != 7:
            fail('structure', f'Round {r}: expected 7 matches')
        for t in team:
            if len(appearances[t, r]) != 1:
                fail('participation', f'Round {r}: {t} must appear once')
        if Counter(m['slot'] for m in ms) != Counter(slot.keys()):
            fail('slots', f'Round {r}: slots must each be used once')
        hosts = Counter((team[m['home']]['home_conflict_group'], slot[m['slot']]['day'])
                        for m in ms if team[m['home']]['home_conflict_group'])
        if any(v > rules['max_home_per_conflict_group_per_day'] for v in hosts.values()):
            fail('geography', f'Round {r}: protected hosts on same day')
        saturday_big = sum(
            (team[m['home']]['category'] == 'big') +
            (team[m['away']]['category'] == 'big')
            for m in ms if slot[m['slot']]['day'] == 'saturday')
        if saturday_big > rules['max_big_teams_saturday']:
            fail('saturday_big', f'Round {r}: {saturday_big} big teams on Saturday')
        if rules['derby_slot_rules_enabled']:
            derbies = [m for m in ms if derby_kind(team[m['home']], team[m['away']])]
            big = [m for m in derbies
                   if derby_kind(team[m['home']], team[m['away']]) == 'big']
            small = [m for m in derbies
                     if derby_kind(team[m['home']], team[m['away']]) == 'small']
            if len(derbies) == 1:
                m = derbies[0]
                balander_pair = all(team[m[k]]['category'] == 'balander'
                                    for k in ('home', 'away'))
                expected_slot = 'S3' if balander_pair else 'S7'
                if m['slot'] != expected_slot:
                    fail('derby_slots', f'Round {r}: single derby requires {expected_slot}')
            elif len(derbies) == 2:
                if len(big) == 2 or len(small) == 2:
                    if sorted(m['slot'] for m in derbies) != ['S6', 'S7']:
                        fail('derby_slots', f'Round {r}: two same-type derbies require S6/S7')
                else:
                    m = small[0]
                    balander_pair = all(team[m[k]]['category'] == 'balander'
                                        for k in ('home', 'away'))
                    expected_slot = 'S3' if balander_pair else 'S6'
                    if m['slot'] != expected_slot or big[0]['slot'] != 'S7':
                        fail('derby_slots', f'Round {r}: mixed derbies require {expected_slot}/S7')
        count = sum(derby_kind(team[m['home']], team[m['away']]) is not None for m in ms)
        if count > (0 if r in rules['no_derby_rounds'] else rules['max_derbies_per_round']):
            fail('derbies', f'Round {r}: {count} derbies')
    for pair in combinations(sorted(team), 2):
        ms = pairs[pair]
        halves = [[m for m in ms if lo <= m['round'] <= hi] for lo, hi in ((1, 13), (14, 26))]
        if any(len(half) != 1 for half in halves):
            fail('pairings', f'{pair}: expected one meeting per half')
            continue
        first, second = halves[0][0], halves[1][0]
        if first['home'] != second['away'] or first['away'] != second['home']:
            fail('venues', f'{pair}: venues not reversed')
        if second['round'] - first['round'] < rules['min_rematch_round_difference']:
            fail('rematches', f'{pair}: rematches too close')
    for t in team:
        for r in range(1, 25):
            window = [appearances[t, rr] for rr in range(r, r + 3)]
            if all(len(v) == 1 for v in window) and len({v[0] for v in window}) == 1:
                fail('streaks', f'{t}: three identical venues at rounds {r}–{r + 2}')
    return {'valid': not any(errors.values()),
            'checks': {key: {'passed': not value, 'errors': value} for key, value in errors.items()}}


def read_schedule(path):
    path = Path(path)
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8', newline='') as stream:
            records = list(csv.DictReader(stream))
        for m in records:
            m['round'] = int(m['round'])
            m['derby'] = m['derby'] or None
        return records
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('schedule', type=Path)
    parser.add_argument('--input-dir', type=Path, default=Path('data'))
    parser.add_argument('--output-dir', type=Path, default=Path('outputs'))
    args = parser.parse_args()
    try:
        report = validate_schedule(read_schedule(args.schedule), *load_inputs(args.input_dir))
    except (ValueError, KeyError, OSError, TypeError) as exc:
        report = {'valid': False, 'error': str(exc)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
