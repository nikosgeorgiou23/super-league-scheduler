"""Run CP-SAT, export records and independently validate the saved files."""
import argparse
import csv
import json
import math
from pathlib import Path
from ortools.sat.python import cp_model
from .data import load_inputs, derby_kind
from .model import build_model
from .validate import read_schedule, validate_schedule


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


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
    status = solver.solve(model)
    result = {'status': solver.status_name(status), 'time_limit': time_limit, 'seed': seed,
              'wall_time': solver.wall_time, 'validated': False,
              'response_stats': solver.response_stats()}
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        matches = []
        for (r, h, a, s), var in variables.items():
            if solver.value(var):
                matches.append(dict(round=r + 1, home=teams[h]['id'], away=teams[a]['id'],
                                    home_name=teams[h]['name'], away_name=teams[a]['name'],
                                    venue=teams[h]['id'], slot=slots[s]['id'],
                                    day=slots[s]['day'], start_earliest=slots[s]['start_earliest'],
                                    start_latest=slots[s]['start_latest'], derby=derby_kind(teams[h], teams[a])))
        matches.sort(key=lambda m: (m['round'], m['slot']))
        write_json(output_dir / 'schedule.json', matches)
        with (output_dir / 'schedule.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(matches[0]))
            writer.writeheader()
            writer.writerows(matches)
        write_json(output_dir / 'by_team.json', {t['id']: [m for m in matches if t['id'] in (m['home'], m['away'])] for t in teams})
        reports = {ext: validate_schedule(read_schedule(output_dir / f'schedule.{ext}'), *load_inputs(input_dir))
                   for ext in ('json', 'csv')}
        result['validated'] = all(r['valid'] for r in reports.values())
        write_json(output_dir / 'validation.json', reports)
    write_json(output_dir / 'status.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, default=Path('data'))
    parser.add_argument('--output-dir', type=Path, default=Path('outputs'))
    parser.add_argument('--time-limit', type=float, default=120)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()
    try:
        result = solve(args.input_dir, args.output_dir, args.time_limit, args.seed)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['validated'] else {'INFEASIBLE': 2, 'UNKNOWN': 3, 'MODEL_INVALID': 4}.get(result['status'], 1)


if __name__ == '__main__':
    raise SystemExit(main())
