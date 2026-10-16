"""Run CP-SAT, export records and independently validate the saved files."""
import argparse
import csv
import json
import math
import time
from datetime import datetime
from pathlib import Path
from ortools.sat.python import cp_model
from .data import load_inputs, derby_kind
from .model import build_model
from .validate import read_schedule, validate_schedule


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def print_schedule(matches):
    """Display the exported matches grouped by round in the terminal."""
    current_round = None
    for match in matches:
        if match['round'] != current_round:
            current_round = match['round']
            print(f'\nΑγωνιστική {current_round}')
        derby = f" | Ντέρμπι: {match['derby']}" if match['derby'] else ''
        print(f"  {match['slot']} | {match['day']} | "
              f"{match['start_earliest']}-{match['start_latest']} | "
              f"{match['home_name']} - {match['away_name']}{derby}")


def extract_matches(value, variables, teams, slots):
    matches = []
    for (r, h, a, s), var in variables.items():
        if value(var):
            matches.append(dict(round=r + 1, home=teams[h]['id'], away=teams[a]['id'],
                                home_name=teams[h]['name'], away_name=teams[a]['name'],
                                venue=teams[h]['id'], slot=slots[s]['id'],
                                day=slots[s]['day'], start_earliest=slots[s]['start_earliest'],
                                start_latest=slots[s]['start_latest'], derby=derby_kind(teams[h], teams[a])))
    matches.sort(key=lambda m: (m['round'], m['slot']))
    return matches


def export_schedule(output_dir, matches, teams, slots, rules):
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / 'schedule.json', matches)
    with (output_dir / 'schedule.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(matches[0]))
        writer.writeheader()
        writer.writerows(matches)
    write_json(output_dir / 'by_team.json', {t['id']: [m for m in matches if t['id'] in (m['home'], m['away'])] for t in teams})
    reports = {ext: validate_schedule(read_schedule(output_dir / f'schedule.{ext}'), teams, slots, rules)
               for ext in ('json', 'csv')}
    write_json(output_dir / 'validation.json', reports)
    return all(r['valid'] for r in reports.values())


def solve(input_dir, output_dir, time_limit=120, seed=0):
    if not math.isfinite(time_limit) or time_limit <= 0 or not 0 <= seed <= 2147483647:
        raise ValueError('Time limit must be positive and finite; seed must be 0..2147483647')
    teams, slots, rules = load_inputs(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Reject reused directories to avoid presenting a stale schedule after UNKNOWN.
    if any((output_dir / name).exists() for name in ('schedule.json', 'schedule.csv', 'status.json')):
        raise ValueError('Use a fresh output directory')
    model, variables = build_model(teams, slots, rules)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = 8
    solver.parameters.stop_after_first_solution = True
    status = solver.solve(model)
    result = {'status': solver.status_name(status), 'time_limit': time_limit, 'seed': seed,
              'wall_time': solver.wall_time, 'validated': False,
              'response_stats': solver.response_stats()}
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        matches = extract_matches(solver.value, variables, teams, slots)
        result['validated'] = export_schedule(output_dir, matches, teams, slots, rules)
    write_json(output_dir / 'status.json', result)
    return result


def exclude_similar_schedule(model, variables, value, min_different_matches):
    """Require changed pairings per round, ignoring slots and home/away."""
    previous = {(r, min(h, a), max(h, a))
                for (r, h, a, s), var in variables.items() if value(var)}
    unchanged = [var for (r, h, a, s), var in variables.items()
                 if (r, min(h, a), max(h, a)) in previous]
    model.add(sum(unchanged) <= len(previous) - min_different_matches)


def solve_many(input_dir, output_dir, time_limit=60, seed=0, min_different_matches=20):
    """Compatibility entry point: export only the first feasible schedule."""
    if not math.isfinite(time_limit) or time_limit <= 0 or not 0 <= seed <= 2147483647:
        raise ValueError('Time limit must be positive and finite; seed must be 0..2147483647')
    if not 1 <= min_different_matches <= 182:
        raise ValueError('Minimum different matches must be 1..182')
    started = time.monotonic()
    teams, slots, rules = load_inputs(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError('Use a fresh output directory')
    model, variables = build_model(teams, slots, rules)
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = 8
    count = 0
    all_valid = True
    last_status = 'UNKNOWN'
    while time.monotonic() - started < time_limit:
        solver.parameters.max_time_in_seconds = time_limit - (time.monotonic() - started)
        solver.parameters.stop_after_first_solution = True
        status = solver.solve(model)
        last_status = solver.status_name(status)
        if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            break
        matches = extract_matches(solver.value, variables, teams, slots)
        count += 1
        destination = output_dir / f'solution_{count:04d}'
        valid = export_schedule(destination, matches, teams, slots, rules)
        all_valid = all_valid and valid
        print(f'\nΠρόγραμμα {count} | {destination} | validated={valid}', flush=True)
        print_schedule(matches)
        # Stop immediately after exporting the first feasible schedule.
        break
    result = {'status': 'FEASIBLE' if count else last_status,
              'last_search_status': last_status, 'solutions': count,
              'validated': count > 0 and all_valid, 'time_limit': time_limit,
              'wall_time': time.monotonic() - started, 'seed': seed,
              'min_different_matches': min_different_matches}
    write_json(output_dir / 'status.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, default=Path('data'))
    parser.add_argument('--output-dir', type=Path, default=Path('outputs'))
    parser.add_argument('--time-limit', type=float, default=60)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--many', action='store_true', help='Compatibility option; stops at the first feasible schedule')
    parser.add_argument('--min-different-matches', type=int, default=20,
                        help='Legacy compatibility option; unused when returning one schedule')
    args = parser.parse_args()
    try:
        if args.many:
            args.output_dir = args.output_dir / datetime.now().strftime('run_%Y%m%d_%H%M%S_%f')
        if args.many:
            result = solve_many(args.input_dir, args.output_dir, args.time_limit, args.seed,
                                args.min_different_matches)
        else:
            result = solve(args.input_dir, args.output_dir, args.time_limit, args.seed)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))
    if not args.many and result['status'] in ('FEASIBLE', 'OPTIMAL'):
        print_schedule(read_schedule(args.output_dir / 'schedule.json'))
    return 0 if result['validated'] else {'INFEASIBLE': 2, 'UNKNOWN': 3, 'MODEL_INVALID': 4}.get(result['status'], 1)


if __name__ == '__main__':
    raise SystemExit(main())
