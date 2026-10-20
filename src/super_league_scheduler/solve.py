"""Run CP-SAT optimization, snapshot inputs, export and independently validate."""
import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
import ortools
from ortools.sat.python import cp_model
from .data import load_inputs, prepare_scenario
from .model import build_model, SCALE, ROUNDING, objective_units
from .validate import read_schedule, validate_export, compute_kpis, mirror_summary


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def print_schedule(matches):
    current_round = None
    for m in matches:
        if m['round'] != current_round:
            current_round = m['round']
            print(f'\nRound {current_round}')
        print(f"  {m['slot']} | {m['day']} | {m['start_earliest']}-{m['start_latest']} | "
              f"{m['home_name']} - {m['away_name']}")


def extract_matches(value, variables, teams, slots):
    matches = []
    for (r, h, a, s), var in variables.items():
        if value(var):
            matches.append(dict(round=r + 1, home=teams[h]['id'], away=teams[a]['id'],
                                home_name=teams[h]['name'], away_name=teams[a]['name'],
                                venue=teams[h]['id'], slot=slots[s]['id'],
                                **{k: slots[s][k] for k in ('day', 'start_earliest', 'start_latest')}))
    return sorted(matches, key=lambda m: (m['round'], m['slot']))


class Progress(cp_model.CpSolverSolutionCallback):
    def __init__(self, optimization):
        super().__init__()
        self.optimization = optimization
        self.history = []

    def on_solution_callback(self):
        objective = self.objective_value if self.optimization else None
        if not self.history or (self.optimization and objective > self.history[-1]['scaled_objective']):
            self.history.append(dict(seconds=self.wall_time, scaled_objective=objective,
                                     scaled_bound=self.best_objective_bound if self.optimization else None))


def solve(input_dir, output_dir, time_limit=120, seed=0, *, data_seed=0, workers=8,
          balance=3, mode='optimization', attractiveness_file=None, scale=SCALE):
    started = time.monotonic()
    if not math.isfinite(time_limit) or time_limit <= 0:
        raise ValueError('Time limit must be positive and finite')
    if any(type(s) is not int or not 0 <= s <= 2147483647 for s in (seed, data_seed)):
        raise ValueError('Seeds must be 0..2147483647')
    if type(workers) is not int or not 1 <= workers <= 256:
        raise ValueError('Workers must be 1..256')
    numerator, denominator = objective_units(balance, scale)
    teams, slots, rules = load_inputs(input_dir)
    root = Path(input_dir)
    source = json.loads((root / 'strength.json').read_text(encoding='utf-8'))
    rating_config = json.loads((root / 'rating_config.json').read_text(encoding='utf-8'))
    reuse = json.loads(Path(attractiveness_file).read_text(encoding='utf-8')) if attractiveness_file else None
    scenario = prepare_scenario(teams, source, rating_config, data_seed, reuse)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError('Use a fresh output directory')
    cfg = dict(time_limit=time_limit, solver_seed=seed, data_seed=scenario['data_seed'], workers=workers,
               balance=balance, mode=mode, scale=scale, rounding_policy=ROUNDING,
               lambda_numerator=numerator, lambda_denominator=denominator,
               objective_divisor=scale * denominator, attractiveness_file=str(attractiveness_file) if attractiveness_file else None)
    write_json(output_dir / 'scenario.json', scenario)
    write_json(output_dir / 'run.json', dict(configuration=cfg, teams=teams, slots=slots, rules=rules,
                                            ortools_version=ortools.__version__))
    model, variables = build_model(teams, slots, rules, scenario, balance, mode, scale)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = workers
    solver.parameters.stop_after_first_solution = mode == 'feasibility'
    write_json(output_dir / 'solver_parameters.json', dict(max_time_in_seconds=time_limit,
               random_seed=seed, num_search_workers=workers, stop_after_first_solution=mode == 'feasibility'))
    progress = Progress(mode == 'optimization')
    status = solver.solve(model, progress)
    result = dict(status=solver.status_name(status), configuration=cfg, ortools_version=ortools.__version__,
                  wall_time=solver.wall_time, total_time=time.monotonic() - started, validated=False,
                  first_solution_time=progress.history[0]['seconds'] if progress.history else None,
                  improvements=progress.history, response_stats=solver.response_stats(),
                  scaled_objective=None, scaled_bound=None, relative_gap=None,
                  gap_definition='(scaled_bound - scaled_objective) / max(1, abs(scaled_objective)); rounded integer objective only')
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        matches = extract_matches(solver.value, variables, teams, slots)
        result['kpis'] = compute_kpis(matches, slots, scenario, balance, scale)
        result['mirrors'] = mirror_summary(matches)
        if mode == 'optimization':
            result['scaled_objective'] = solver.objective_value
            result['scaled_bound'] = solver.best_objective_bound
            result['relative_gap'] = max(0, (solver.best_objective_bound - solver.objective_value) / max(1, abs(solver.objective_value)))
        write_json(output_dir / 'schedule.json', matches)
        with (output_dir / 'schedule.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(matches[0]))
            writer.writeheader()
            writer.writerows(matches)
        write_json(output_dir / 'by_team.json', {t['id']: [m for m in matches if t['id'] in (m['home'], m['away'])] for t in teams})
        write_json(output_dir / 'status.json', result)
        reports = {ext: validate_export(output_dir / f'schedule.{ext}', input_dir) for ext in ('json', 'csv')}
        write_json(output_dir / 'validation.json', reports)
        result['validated'] = all(r['valid'] for r in reports.values())
    result['total_time'] = time.monotonic() - started
    write_json(output_dir / 'status.json', result)
    return result


def solve_many(input_dir, output_dir, time_limit=60, seed=0, min_different_matches=20, **kwargs):
    """Legacy alias: same complete optimization as solve; no diversity cuts."""
    return solve(input_dir, output_dir, time_limit, seed, **kwargs)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, default=Path('data'))
    parser.add_argument('--output-dir', type=Path, default=Path('outputs'))
    parser.add_argument('--time-limit', type=float, default=120)
    parser.add_argument('--solver-seed', '--seed', dest='seed', type=int, default=0)
    parser.add_argument('--data-seed', type=int, default=0)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--lambda', dest='balance', type=float, default=3)
    parser.add_argument('--mode', choices=['optimization', 'feasibility'], default='optimization')
    parser.add_argument('--attractiveness-file', type=Path)
    parser.add_argument('--scale', type=int, default=SCALE)
    parser.add_argument('--many', action='store_true', help='Legacy alias; runs normal optimization in a new directory')
    parser.add_argument('--min-different-matches', type=int, default=20, help='Deprecated; ignored')
    args = parser.parse_args()
    try:
        if args.many:
            args.output_dir = args.output_dir / datetime.now().strftime('run_%Y%m%d_%H%M%S_%f')
        result = solve(args.input_dir, args.output_dir, args.time_limit, args.seed,
                       data_seed=args.data_seed, workers=args.workers, balance=args.balance,
                       mode=args.mode, attractiveness_file=args.attractiveness_file, scale=args.scale)
    except (ValueError, KeyError, OSError, TypeError, OverflowError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=True))
    if result['status'] in ('FEASIBLE', 'OPTIMAL'):
        print_schedule(read_schedule(args.output_dir / 'schedule.json'))
    return 0 if result['validated'] else {'INFEASIBLE': 2, 'UNKNOWN': 3, 'MODEL_INVALID': 4}.get(result['status'], 1)


if __name__ == '__main__':
    raise SystemExit(main())
