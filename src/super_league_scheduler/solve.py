"""Run CP-SAT optimization, snapshot inputs, export and independently validate."""
import argparse
import csv
import json
import importlib.util
import math
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import ortools
from ortools.sat.python import cp_model
from .data import load_inputs, prepare_scenario
from .model import build_model, SCALE, ROUNDING, objective_units
from .validate import read_schedule, validate_export, compute_kpis, mirror_summary


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_records(output_dir, matches, prefix='schedule'):
    write_json(output_dir / f'{prefix}.json', matches)
    with (output_dir / f'{prefix}.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(matches[0]))
        writer.writeheader()
        writer.writerows(matches)


def write_history(output_dir, history):
    write_json(output_dir / 'alns_history.json', history)
    fields = list(history[0]) if history else ['iteration', 'operator', 'repair_status']
    with (output_dir / 'alns_history.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for event in history:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in event.items()})


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
          balance=3, mode='optimization', attractiveness_file=None, scale=SCALE,
          alns_config=None):
    started = time.monotonic()
    if not math.isfinite(time_limit) or time_limit <= 0:
        raise ValueError('Time limit must be positive and finite')
    if any(type(s) is not int or not 0 <= s <= 2147483647 for s in (seed, data_seed)):
        raise ValueError('Seeds must be 0..2147483647')
    if type(workers) is not int or not 1 <= workers <= 256:
        raise ValueError('Workers must be 1..256')
    if alns_config is not None:
        alns_config.validate()
        if balance != 3 or mode != 'optimization':
            raise ValueError('ALNS requires --lambda 3 and optimization mode')
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
    if alns_config is not None:
        cfg['alns'] = asdict(alns_config)
    write_json(output_dir / 'scenario.json', scenario)
    write_json(output_dir / 'run.json', dict(configuration=cfg, teams=teams, slots=slots, rules=rules,
                                            ortools_version=ortools.__version__))
    model, variables = build_model(teams, slots, rules, scenario, balance, mode, scale)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = workers
    solver.parameters.stop_after_first_solution = mode == 'feasibility' or alns_config is not None
    write_json(output_dir / 'solver_parameters.json', dict(max_time_in_seconds=time_limit,
               random_seed=seed, num_search_workers=workers,
               stop_after_first_solution=mode == 'feasibility' or alns_config is not None))
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
        if alns_config is not None:
            from .alns import evaluate, CPSatRepair, search
            # Independent initial validation happens before the ALNS clock.
            validation_start = time.monotonic()
            initial_evaluation = evaluate(matches, teams, slots, rules, scenario, scale)
            result['initial_validation_time'] = time.monotonic() - validation_start
            write_records(output_dir, matches, 'initial_schedule')
            initial_gap = max(0, (solver.best_objective_bound - initial_evaluation.score) /
                              max(1, abs(initial_evaluation.score)))
            initial = dict(kpis=initial_evaluation.kpis, scaled_bound=solver.best_objective_bound,
                           relative_gap=initial_gap, first_solution_time=result['first_solution_time'])
            write_json(output_dir / 'initial_summary.json', initial)
            print('\nINITIAL VERIFIED SCHEDULE', flush=True)
            print_schedule(matches)
            print(f"Initial Z={initial_evaluation.kpis['Z']:.6f}; "
                  f"rounded objective={initial_evaluation.score / cfg['objective_divisor']:.6f}; "
                  f"global gap={initial_gap:.2%}\nStarting ALNS for {alns_config.seconds:g} seconds", flush=True)
            repair = CPSatRepair(model, variables, teams, slots,
                                 lambda value: extract_matches(value, variables, teams, slots),
                                 workers, seed, alns_config.verbose)
            matches, current, report, history = search(
                matches, initial_evaluation, [t['id'] for t in teams],
                lambda candidate: evaluate(candidate, teams, slots, rules, scenario, scale),
                repair, alns_config, cfg['objective_divisor'])
            report.update(global_scaled_bound=solver.best_objective_bound,
                          relative_gap=max(0, (solver.best_objective_bound - report['best_scaled_objective']) /
                                           max(1, abs(report['best_scaled_objective']))))
            write_records(output_dir, current, 'current_schedule')
            write_json(output_dir / 'alns_summary.json', report)
            write_history(output_dir, history)
            result.update(alns=report, initial=initial, initial_search_wall_time=solver.wall_time,
                          response_stats_scope='initial full-model search only')
            result['wall_time'] += sum(event['solver_seconds'] for event in history)
            result['improvements'].extend(dict(seconds=solver.wall_time + event['elapsed'],
                                               scaled_objective=event['best_scaled_objective'],
                                               scaled_bound=solver.best_objective_bound, phase='alns')
                                           for event in history if event['note'] == 'NEW BEST')
        result['kpis'] = compute_kpis(matches, slots, scenario, balance, scale)
        result['mirrors'] = mirror_summary(matches)
        if mode == 'optimization':
            result['scaled_objective'] = result['kpis']['scaled_objective']
            result['scaled_bound'] = solver.best_objective_bound
            result['relative_gap'] = max(0, (result['scaled_bound'] - result['scaled_objective']) / max(1, abs(result['scaled_objective'])))
        if alns_config is not None:
            result['status'] = 'OPTIMAL' if result['relative_gap'] == 0 else 'FEASIBLE'
        write_records(output_dir, matches)
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
    parser.add_argument('--show-chart', action='store_true', help='Save and open the round TV-value chart after a validated solution')
    parser.add_argument('--alns', action='store_true', help='First feasible solution followed by adaptive repair and simulated annealing (lambda=3)')
    parser.add_argument('--alns-time', type=float, default=240)
    parser.add_argument('--alns-seed', type=int, default=0)
    parser.add_argument('--alns-worst-pool', type=int, default=5)
    parser.add_argument('--alns-random-rounds-time', type=float, default=3)
    parser.add_argument('--alns-worst-value-rounds-time', type=float, default=3)
    parser.add_argument('--alns-random-teams-time', type=float, default=5)
    parser.add_argument('--alns-calibration-time', type=float, default=15)
    parser.add_argument('--alns-verbose', action='store_true')
    parser.add_argument('--many', action='store_true', help='Legacy alias; runs normal optimization in a new directory')
    parser.add_argument('--min-different-matches', type=int, default=20, help='Deprecated; ignored')
    args = parser.parse_args()
    if args.show_chart and importlib.util.find_spec('matplotlib') is None:
        parser.error('Chart requires matplotlib: python -m pip install -e ".[plot]"')
    try:
        if args.many:
            args.output_dir = args.output_dir / datetime.now().strftime('run_%Y%m%d_%H%M%S_%f')
        options = {}
        if args.alns:
            from .alns import ALNSConfig
            options['alns_config'] = ALNSConfig(
                seconds=args.alns_time, seed=args.alns_seed, worst_pool=args.alns_worst_pool,
                random_rounds_seconds=args.alns_random_rounds_time,
                worst_value_rounds_seconds=args.alns_worst_value_rounds_time,
                random_teams_seconds=args.alns_random_teams_time,
                calibration_seconds=args.alns_calibration_time, verbose=args.alns_verbose)
        result = solve(args.input_dir, args.output_dir, args.time_limit, args.seed,
                       data_seed=args.data_seed, workers=args.workers, balance=args.balance,
                       mode=args.mode, attractiveness_file=args.attractiveness_file, scale=args.scale,
                       **options)
    except (ValueError, KeyError, OSError, TypeError, OverflowError) as exc:
        parser.error(str(exc))
    if args.alns:
        print(f"Result: {result['status']} | validated={result['validated']} | {args.output_dir / 'status.json'}")
    else:
        print(json.dumps(result, ensure_ascii=True))
    if result['status'] in ('FEASIBLE', 'OPTIMAL'):
        if 'alns' in result:
            print('\nBEST ALNS SCHEDULE')
        print_schedule(read_schedule(args.output_dir / 'schedule.json'))
        if 'alns' in result:
            report = result['alns']
            print(f"ALNS: {report['iterations']} iterations; accepted worse={report['accepted_worse']}; "
                  f"initial Z={report['initial_real_Z']:.6f}; best Z={report['best_real_Z']:.6f}; "
                  f"global integer-objective gap={result['relative_gap']:.2%}", flush=True)
            for operator, stats in report['operator_statistics'].items():
                print(f"  {operator}: uses={stats['uses']}, accepted={stats['accepted']}, "
                      f"new best={stats['new_best']}, SA worse={stats['accepted_worse']}, "
                      f"weight={report['weights'][operator]:.4f}", flush=True)
        if args.show_chart and result['validated']:
            from .plot import plot_round_values
            chart = plot_round_values(result['kpis']['round_values'], args.output_dir / 'round_tv_value.png', show=True)
            print(f'Chart: {chart}')
    else:
        print(f"No schedule found. Status: {result['status']}. No chart generated. See {args.output_dir / 'status.json'}")
    return 0 if result['validated'] else {'INFEASIBLE': 2, 'UNKNOWN': 3, 'MODEL_INVALID': 4}.get(result['status'], 1)


if __name__ == '__main__':
    raise SystemExit(main())
