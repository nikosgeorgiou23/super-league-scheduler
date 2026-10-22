"""Adaptive neighborhoods, CP-SAT repair and time-cooled simulated annealing."""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import math
import random
import statistics
import time
from ortools.sat.python import cp_model
from .validate import validate_schedule

OPERATORS = ('random_rounds', 'worst_value_rounds', 'random_teams')
REWARDS = {'new_best': 5, 'improved_current': 3, 'accepted_nonbetter': 1, 'rejected': 0}


@dataclass(frozen=True)
class ALNSConfig:
    seconds: float = 240
    seed: int = 0
    worst_pool: int = 5
    random_rounds_seconds: float = 3
    worst_value_rounds_seconds: float = 3
    random_teams_seconds: float = 5
    calibration_seconds: float = 15
    verbose: bool = False

    def validate(self):
        for v in (self.seconds, self.random_rounds_seconds,
                  self.worst_value_rounds_seconds, self.random_teams_seconds):
            if not math.isfinite(v) or v <= 0:
                raise ValueError('ALNS and repair time limits must be positive and finite')
        if not math.isfinite(self.calibration_seconds) or not 0 <= self.calibration_seconds <= 15:
            raise ValueError('ALNS calibration must be between 0 and 15 seconds')
        if type(self.seed) is not int or not 0 <= self.seed <= 2147483647:
            raise ValueError('ALNS seed must be 0..2147483647')
        if type(self.worst_pool) is not int or not 4 <= self.worst_pool <= 13:
            raise ValueError('ALNS worst-value pool must be 4..13')

    def repair_limit(self, operator):
        return getattr(self, operator + '_seconds')


@dataclass(frozen=True)
class Neighborhood:
    operator: str
    rounds: tuple = ()  # Zero-based round indices.
    teams: tuple = ()   # Stable team IDs.

    def contains(self, match):
        if self.operator == 'random_teams':
            return match['home'] in self.teams or match['away'] in self.teams
        return match['round'] - 1 in self.rounds

    def contains_key(self, key, teams):
        r, h, a, _ = key
        if self.operator == 'random_teams':
            return teams[h]['id'] in self.teams or teams[a]['id'] in self.teams
        return r in self.rounds


def destroy(operator, matches, round_values, team_ids, rng, worst_pool=5):
    if operator == 'random_teams':
        return Neighborhood(operator, teams=tuple(sorted(rng.sample(sorted(team_ids), 2))))
    if operator not in OPERATORS:
        raise ValueError('Unknown ALNS operator')
    half, k = rng.randrange(2), rng.choice((2, 3, 4))
    pool = list(range(half * 13, (half + 1) * 13))
    if operator == 'worst_value_rounds':
        pool = sorted(pool, key=lambda r: (round_values[r], r))[:worst_pool]
    return Neighborhood(operator, rounds=tuple(sorted(rng.sample(pool, k))))


def assignments(matches):
    return {(m['round'], m['home'], m['away'], m['slot']) for m in matches}


def unchanged_outside(before, after, neighborhood):
    return (assignments([m for m in before if not neighborhood.contains(m)]) ==
            assignments([m for m in after if not neighborhood.contains(m)]))


def assignment_keys(matches, teams, slots):
    ids = {t['id']: i for i, t in enumerate(teams)}
    slot_ids = {s['id']: i for i, s in enumerate(slots)}
    return {(m['round'] - 1, ids[m['home']], ids[m['away']], slot_ids[m['slot']]) for m in matches}


def build_repair(base, variables, matches, teams, slots, neighborhood):
    """Clone the full model, explicitly fix its complement, add a local no-good."""
    model = base.clone()
    model.clear_hints()
    selected = assignment_keys(matches, teams, slots)
    free_active, locked_zeros = [], []
    for key, var in variables.items():
        if neighborhood.contains_key(key, teams):
            if key in selected:
                free_active.append(var)
        elif key in selected:
            model.add(var == 1)
        else:
            locked_zeros.append(var)
    # A zero sum of nonnegative Booleans fixes every unselected outside choice.
    model.add(sum(locked_zeros) == 0)
    if not free_active:
        raise ValueError('Empty ALNS neighborhood')
    model.add(sum(free_active) <= len(free_active) - 1)
    for key in selected:
        model.add_hint(variables[key], 1)
    return model, len(free_active)


@dataclass
class RepairResult:
    status: str
    candidate: list | None = None
    duration: float = 0
    solver_seconds: float = 0
    solver_limit: float = 0
    free_matches: int = 0
    diagnostics: str | None = None


class CPSatRepair:
    def __init__(self, base, variables, teams, slots, extract, workers, solver_seed,
                 verbose=False, clock=time.monotonic):
        self.base, self.variables = base, variables
        self.teams, self.slots, self.extract = teams, slots, extract
        self.workers, self.solver_seed = workers, solver_seed
        self.verbose, self.clock = verbose, clock

    def __call__(self, current, neighborhood, deadline, limit, iteration):
        start = self.clock()
        if start >= deadline:
            return RepairResult('NOT_RUN_BUDGET')
        model, free_matches = build_repair(self.base, self.variables, current,
                                           self.teams, self.slots, neighborhood)
        remaining = min(limit, deadline - self.clock())
        if remaining <= 0:
            return RepairResult('NOT_RUN_BUDGET', duration=self.clock() - start,
                                free_matches=free_matches)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = remaining
        solver.parameters.num_search_workers = self.workers
        solver.parameters.random_seed = (self.solver_seed + iteration) % 2147483648
        solver.parameters.stop_after_first_solution = False
        solver.parameters.log_search_progress = self.verbose
        status = solver.solve(model)
        if status == cp_model.MODEL_INVALID:
            raise ValueError(f'Invalid ALNS repair model: {solver.response_stats()}')
        candidate = self.extract(solver.value) if status in (cp_model.FEASIBLE, cp_model.OPTIMAL) else None
        # A repair bound is intentionally never returned as a global bound.
        return RepairResult(solver.status_name(status), candidate, self.clock() - start,
                            solver.wall_time, remaining, free_matches,
                            solver.response_stats() if self.verbose else None)


@dataclass(frozen=True)
class Evaluation:
    score: int
    kpis: dict


def evaluate(matches, teams, slots, rules, scenario, scale):
    report = validate_schedule(matches, teams, slots, rules, scenario, balance=3, scale=scale)
    if not report['valid']:
        failed = [name for name, check in report['checks'].items() if not check['passed']]
        raise ValueError('Independent ALNS validation failed: ' + ', '.join(failed))
    return Evaluation(report['kpis']['scaled_objective'], report['kpis'])


def reference_loss(losses, initial_score, divisor):
    fallback = not losses
    loss = max(0.001 * divisor, 0.01 * abs(initial_score)) if fallback else statistics.median(losses)
    return float(loss), fallback


def temperature_at(loss, elapsed, budget):
    start, end = -loss / math.log(0.50), -loss / math.log(0.01)
    progress = min(1.0, max(0.0, elapsed / budget)) if budget > 0 else 1.0
    return start * (end / start) ** progress


def sa_accept(delta, temperature, rng, calibration=False):
    if delta >= 0:
        return True, 1.0, None
    probability = 0.0 if calibration or temperature <= 0 else math.exp(delta / temperature)
    draw = None if calibration else rng.random()
    return (draw is not None and draw < probability), probability, draw


@dataclass
class SearchState:
    current: list
    best: list
    current_eval: Evaluation
    best_eval: Evaluation

    @classmethod
    def initial(cls, solution, evaluation):
        return cls(deepcopy(solution), deepcopy(solution), deepcopy(evaluation), deepcopy(evaluation))

    def consider(self, candidate, evaluation, temperature, rng, calibration=False):
        delta = evaluation.score - self.current_eval.score
        accepted, probability, draw = sa_accept(delta, temperature, rng, calibration)
        reward = 0
        note = 'REJECTED'
        if accepted:
            self.current, self.current_eval = deepcopy(candidate), deepcopy(evaluation)
            if evaluation.score > self.best_eval.score:
                self.best, self.best_eval = deepcopy(candidate), deepcopy(evaluation)
                reward, note = 5, 'NEW BEST'
            elif delta > 0:
                reward, note = 3, 'IMPROVED CURRENT'
            elif delta == 0:
                reward, note = 1, 'ACCEPTED EQUAL'
            else:
                reward, note = 1, 'SA ACCEPTED (worse)'
        return dict(accepted=accepted, probability=probability, draw=draw,
                    delta_scaled=delta, reward=reward, note=note)


@dataclass
class AdaptiveWeights:
    weights: dict = field(default_factory=lambda: dict.fromkeys(OPERATORS, 1.0))
    uses: dict = field(default_factory=lambda: dict.fromkeys(OPERATORS, 0))
    rewards: dict = field(default_factory=lambda: dict.fromkeys(OPERATORS, 0))
    count: int = 0

    def probabilities(self):
        total = sum(self.weights.values())
        return {op: self.weights[op] / total for op in OPERATORS}

    def record(self, operator, reward):
        self.uses[operator] += 1
        self.rewards[operator] += reward
        self.count += 1
        if self.count == 20:
            for op in OPERATORS:
                if self.uses[op]:
                    self.weights[op] = max(0.1, 0.8 * self.weights[op] +
                                           0.2 * self.rewards[op] / self.uses[op])
            self.uses = dict.fromkeys(OPERATORS, 0)
            self.rewards = dict.fromkeys(OPERATORS, 0)
            self.count = 0
            return True
        return False


def live_line(iteration, current, best, divisor, note):
    print(f'{iteration:<10}{current / divisor:>18.4f}{best / divisor:>18.4f}    {note}', flush=True)


def search(initial, initial_eval, team_ids, evaluator, repair, config, divisor,
           clock=time.monotonic, on_iteration=None):
    """Budget starts here, after the caller has independently validated initial."""
    config.validate()
    start = clock()
    deadline = start + config.seconds
    calibration_deadline = start + min(config.calibration_seconds, config.seconds)
    state = SearchState.initial(initial, initial_eval)
    rng = random.Random(config.seed)
    adaptive = AdaptiveWeights()
    statistics_by_op = {op: dict(uses=0, valid_candidates=0, accepted=0, accepted_worse=0,
                                 new_best=0, reward_sum=0, solver_seconds=0.0,
                                 repair_seconds=0.0, statuses={}) for op in OPERATORS}
    losses, history, weight_updates = [], [], []
    calibration = None
    print(f"{'Iteration':<10}{'Current solution':>18}{'Best solution':>18}    Note", flush=True)
    live_line(0, state.current_eval.score, state.best_eval.score, divisor, 'INITIAL')

    def finish_calibration(now):
        loss, fallback = reference_loss(losses, initial_eval.score, divisor)
        info = dict(duration=now - start, requested_seconds=config.calibration_seconds,
                    loss_samples_scaled=list(losses), reference_loss_scaled=loss,
                    reference_loss=loss / divisor, fallback_used=fallback,
                    temperature_start_scaled=temperature_at(loss, 0, 1),
                    temperature_end_scaled=temperature_at(loss, 1, 1),
                    temperature_start=temperature_at(loss, 0, 1) / divisor,
                    temperature_end=temperature_at(loss, 1, 1) / divisor,
                    main_start=now, main_budget=max(0.0, deadline - now))
        print(f"Calibration complete: L_ref={info['reference_loss']:.6f}; "
              f"fallback={fallback}; T_start={info['temperature_start']:.6f}; "
              f"T_end={info['temperature_end']:.6f}", flush=True)
        return info

    while True:
        now = clock()
        if calibration is None and now >= calibration_deadline:
            calibration = finish_calibration(now)
        if now >= deadline:
            break
        is_calibration = calibration is None
        probs = dict.fromkeys(OPERATORS, 1 / 3) if is_calibration else adaptive.probabilities()
        op = rng.choices(OPERATORS, weights=[probs[k] for k in OPERATORS], k=1)[0]
        neighborhood = destroy(op, state.current, state.current_eval.kpis['round_values'],
                               team_ids, rng, config.worst_pool)
        iteration = len(history) + 1
        before = state.current_eval.score
        weights_before = dict(adaptive.weights)
        result = repair(state.current, neighborhood,
                        calibration_deadline if is_calibration else deadline,
                        config.repair_limit(op), iteration)
        decision = dict(accepted=False, probability=None, draw=None, delta_scaled=None,
                        reward=0, note='REPAIR ' + result.status)
        evaluation = None
        temperature = None
        if not is_calibration:
            temperature = temperature_at(calibration['reference_loss_scaled'],
                                         clock() - calibration['main_start'],
                                         calibration['main_budget'])
        error = None
        if result.candidate is not None:
            try:
                if not unchanged_outside(state.current, result.candidate, neighborhood):
                    raise ValueError('Repair changed assignments outside the neighborhood')
                evaluation = evaluator(result.candidate)
                if assignments(result.candidate) == assignments(state.current):
                    decision['note'] = 'REPAIR IDENTICAL'
                else:
                    loss = before - evaluation.score
                    if is_calibration and loss > 0:
                        losses.append(loss)
                    decision = state.consider(result.candidate, evaluation, temperature or 0,
                                              rng, is_calibration)
            except ValueError as exc:
                error = str(exc)
                evaluation = None
                decision['note'] = 'REPAIR INVALID CANDIDATE'
        updated = adaptive.record(op, decision['reward'])
        stats = statistics_by_op[op]
        stats['uses'] += 1
        stats['valid_candidates'] += evaluation is not None
        stats['accepted'] += decision['accepted']
        stats['accepted_worse'] += decision['accepted'] and decision['delta_scaled'] < 0
        stats['new_best'] += decision['note'] == 'NEW BEST'
        stats['reward_sum'] += decision['reward']
        stats['solver_seconds'] += result.solver_seconds
        stats['repair_seconds'] += result.duration
        stats['statuses'][result.status] = stats['statuses'].get(result.status, 0) + 1
        event = dict(iteration=iteration, phase='calibration' if is_calibration else 'search',
                     elapsed=clock() - start, operator=op,
                     free_rounds=[r + 1 for r in neighborhood.rounds], free_teams=list(neighborhood.teams),
                     free_matches=result.free_matches, repair_status=result.status,
                     repair_duration=result.duration, solver_seconds=result.solver_seconds,
                     solver_limit=result.solver_limit, candidate_scaled_objective=evaluation.score if evaluation else None,
                     candidate_objective=evaluation.score / divisor if evaluation else None,
                     candidate_real_Z=evaluation.kpis['Z'] if evaluation else None,
                     previous_current_scaled_objective=before,
                     current_scaled_objective=state.current_eval.score,
                     best_scaled_objective=state.best_eval.score,
                     current_objective=state.current_eval.score / divisor,
                     best_objective=state.best_eval.score / divisor,
                     current_real_Z=state.current_eval.kpis['Z'], best_real_Z=state.best_eval.kpis['Z'],
                     delta=decision['delta_scaled'] / divisor if decision['delta_scaled'] is not None else None,
                     temperature_scaled=temperature, temperature=temperature / divisor if temperature is not None else None,
                     operator_probabilities=probs, weights_before=weights_before, weights_after=dict(adaptive.weights),
                     weights_updated=updated, error=error, diagnostics=result.diagnostics, **decision)
        history.append(event)
        if updated:
            weight_updates.append(dict(iteration=iteration, weights=dict(adaptive.weights)))
        note = ('CALIBRATION: ' if is_calibration else '') + decision['note']
        live_line(iteration, state.current_eval.score, state.best_eval.score, divisor, note)
        if on_iteration:
            on_iteration(event)
    end = clock()
    if calibration is None:
        calibration = finish_calibration(end)
    calibration.pop('main_start')
    report = dict(configuration=asdict(config), objective_basis='scaled integer full-season objective / divisor',
                  objective_divisor=divisor, initial_scaled_objective=initial_eval.score,
                  best_scaled_objective=state.best_eval.score, current_scaled_objective=state.current_eval.score,
                  initial_real_Z=initial_eval.kpis['Z'], best_real_Z=state.best_eval.kpis['Z'],
                  improvement_scaled=state.best_eval.score - initial_eval.score,
                  improvement=(state.best_eval.score - initial_eval.score) / divisor,
                  improvement_real_Z=state.best_eval.kpis['Z'] - initial_eval.kpis['Z'],
                  iterations=len(history), accepted_worse=sum(v['accepted_worse'] for v in statistics_by_op.values()),
                  new_bests=sum(v['new_best'] for v in statistics_by_op.values()),
                  calibration=calibration, wall_time=end - start,
                  overrun=max(0.0, end - deadline), weights=dict(adaptive.weights),
                  pending_segment=dict(uses=adaptive.uses, rewards=adaptive.rewards, count=adaptive.count),
                  weight_updates=weight_updates, operator_statistics=statistics_by_op,
                  rewards=REWARDS, global_bound_source='initial full-model search only; no repair bounds')
    return deepcopy(state.best), deepcopy(state.current), report, history
