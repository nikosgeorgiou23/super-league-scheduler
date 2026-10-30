"""Independent record validation and KPI recomputation; no OR-Tools imports."""
import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from .data import load_inputs, prepare_scenario

CHECKS = ('structure', 'participation', 'pairings', 'venues', 'slots',
          'geography', 'streaks', 'transition', 'mirror', 'metadata', 'kpis')


def compute_kpis(matches, slots, scenario, balance=3, scale=10000):
    if not math.isfinite(balance) or balance < 0 or type(scale) is not int or scale <= 0:
        raise ValueError('Invalid lambda or scale')
    values, integers = [0.0] * 26, [0] * 26
    by_slot = {s['id']: s for s in slots}
    draws = scenario['attractiveness']
    for m in matches:
        r = m['round'] - 1
        value = (draws[m['home']][r] + draws[m['away']][r]) * by_slot[m['slot']]['value']
        values[r] += value
        integers[r] += round(value * scale)
    weight = Fraction(str(balance))
    spread = max(values) - min(values)
    scaled = weight.denominator * sum(integers) - weight.numerator * (max(integers) - min(integers))
    return dict(round_values=values, total=sum(values), minimum=min(values), maximum=max(values),
                range=spread, standard_deviation=statistics.pstdev(values),
                Z=sum(values) - balance * spread, scaled_round_values=integers,
                scaled_objective=scaled, objective_divisor=scale * weight.denominator)


def mirror_summary(matches):
    rounds = defaultdict(set)
    for m in matches:
        rounds[m['round']].add((m['home'], m['away']))
    counts = [len(rounds[r] & {(a, h) for h, a in rounds[r + 13]}) for r in range(1, 14)]
    return dict(match_counts=counts, rounds=[r + 1 for r, n in enumerate(counts) if n == 7],
                total_matches=sum(counts))


def validate_schedule(matches, teams, slots, rules, scenario=None, balance=3, scale=10000, declared_kpis=None):
    errors = {key: [] for key in CHECKS}
    def fail(key, message):
        errors[key].append(message)
    team = {t['id']: t for t in teams}
    slot = {s['id']: s for s in slots}
    if scenario is None:
        raise ValueError('Scenario required to validate attractiveness and strength metadata')
    prepare_scenario(teams, scenario['source'], scenario['rating_config'], reuse=scenario)
    rounds, pairs, appearances = defaultdict(list), defaultdict(list), defaultdict(list)
    opponents = defaultdict(list)
    clean = []
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
                not isinstance(h, str) or not isinstance(a, str) or h not in team or a not in team or h == a or
                not isinstance(s, str) or s not in slot):
            fail('structure', f'Record {index}: invalid round, teams or slot')
            continue
        clean.append(m)
        rounds[r].append(m)
        pairs[tuple(sorted((h, a)))].append(m)
        appearances[h, r].append(True)
        appearances[a, r].append(False)
        opponents[h, r].append(a)
        opponents[a, r].append(h)
        expected = {k: slot[s][k] for k in ('day', 'start_earliest', 'start_latest')}
        expected.update(home_name=team[h]['name'], away_name=team[a]['name'], venue=h)
        for key, value in expected.items():
            if key not in m or m[key] != value:
                fail('metadata', f'Record {index}: incorrect {key}')
    for r in range(1, 27):
        ms = rounds[r]
        if len(ms) != 7:
            fail('structure', f'Round {r}: expected 7 matches')
        for t in team:
            if len(appearances[t, r]) != 1:
                fail('participation', f'Round {r}: {t} must appear once')
        if len(ms) != 7 or any(count > 1 for count in Counter(m['slot'] for m in ms).values()):
            fail('slots', f'Round {r}: expected 7 distinct slots from S1-S8')
        hosts = Counter((team[m['home']]['home_conflict_group'], slot[m['slot']]['day'])
                        for m in ms if team[m['home']]['home_conflict_group'])
        if any(v > 1 for v in hosts.values()):
            fail('geography', f'Round {r}: protected hosts on same day')
    for pair in combinations(sorted(team), 2):
        ms = pairs[pair]
        halves = [[m for m in ms if lo <= m['round'] <= hi] for lo, hi in ((1, 13), (14, 26))]
        if any(len(half) != 1 for half in halves):
            fail('pairings', f'{pair}: expected one meeting per half')
            continue
        first, second = halves[0][0], halves[1][0]
        if first['home'] != second['away'] or first['away'] != second['home']:
            fail('venues', f'{pair}: venues not reversed')
    for t in team:
        for r in range(1, 25):
            window = [appearances[t, rr] for rr in range(r, r + 3)]
            if all(len(v) == 1 for v in window) and len({v[0] for v in window}) == 1:
                fail('streaks', f'{t}: three consecutive home or away games at rounds {r}-{r + 2}')
        before = set(opponents[t, 13])
        after = set(opponents[t, 14])
        if before & after:
            fail('transition', f'{t}: repeated opponent in rounds 13-14 {sorted(before & after)}')
    mirrors = mirror_summary(clean)
    kpis = compute_kpis(clean, slots, scenario, balance, scale)
    if declared_kpis is not None:
        for k, value in kpis.items():
            actual = declared_kpis.get(k)
            if isinstance(value, list):
                ok = isinstance(actual, list) and len(actual) == len(value) and all(
                    isinstance(a, (int, float)) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-9) for a, b in zip(actual, value))
            else:
                ok = isinstance(actual, (int, float)) and math.isclose(actual, value, rel_tol=1e-10, abs_tol=1e-9)
            if not ok:
                fail('kpis', f'Incorrect declared {k}')
    return {'valid': not any(errors.values()), 'kpis': kpis, 'mirrors': mirrors,
            'checks': {key: {'passed': not value, 'errors': value} for key, value in errors.items()}}


def read_schedule(path):
    path = Path(path)
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as stream:
            records = list(csv.DictReader(stream))
        for m in records:
            m['round'] = int(m['round'])
        return records
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_export(path, input_dir='data'):
    path = Path(path)
    manifest = json.loads((path.parent / 'run.json').read_text(encoding='utf-8'))
    scenario = json.loads((path.parent / 'scenario.json').read_text(encoding='utf-8'))
    status = json.loads((path.parent / 'status.json').read_text(encoding='utf-8'))
    if status['status'] not in ('FEASIBLE', 'OPTIMAL'):
        return {'valid': False, 'error': f"No solution: {status['status']}"}
    local = load_inputs(input_dir)
    if list(local) != [manifest['teams'], manifest['slots'], manifest['rules']]:
        raise ValueError('Input configuration differs from exported snapshot')
    cfg = manifest['configuration']
    report = validate_schedule(read_schedule(path), *local, scenario, cfg['balance'], cfg['scale'], status['kpis'])
    if status.get('mirrors') != report['mirrors']:
        report['valid'] = False
        report['checks']['mirror']['errors'].append('Incorrect declared mirrors')
        report['checks']['mirror']['passed'] = False
    if cfg['mode'] == 'optimization' and status['scaled_objective'] != report['kpis']['scaled_objective']:
        report['valid'] = False
        report['checks']['kpis']['errors'].append('Solver objective differs from recomputed integer objective')
        report['checks']['kpis']['passed'] = False
    if cfg['mode'] == 'optimization':
        objective, bound = status['scaled_objective'], status['scaled_bound']
        expected_gap = (bound - objective) / max(1, abs(objective))
        if not math.isfinite(bound) or bound < objective or not math.isclose(status['relative_gap'], expected_gap, abs_tol=1e-12):
            report['valid'] = False
            report['checks']['kpis']['errors'].append('Inconsistent bound or relative gap')
            report['checks']['kpis']['passed'] = False
    return report


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('schedule', type=Path)
    parser.add_argument('--input-dir', type=Path, default=Path('data'))
    parser.add_argument('--output-dir', type=Path, default=Path('outputs/check'))
    args = parser.parse_args()
    try:
        report = validate_export(args.schedule, args.input_dir)
    except (ValueError, KeyError, OSError, TypeError, OverflowError) as exc:
        report = {'valid': False, 'error': str(exc)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
