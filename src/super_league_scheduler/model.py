"""Unrestricted double round robin and television-value optimization."""
from fractions import Fraction
from itertools import combinations
import math
from ortools.sat.python import cp_model

SCALE = 10000
ROUNDING = 'Python round: nearest integer, ties to even, per match-slot coefficient'


def objective_units(balance, scale=SCALE):
    if not math.isfinite(balance) or balance < 0:
        raise ValueError('Lambda must be nonnegative and finite')
    if type(scale) is not int or scale <= 0:
        raise ValueError('Scale must be a positive integer')
    weight = Fraction(str(balance))
    # Leave headroom below int64 and exact-double reporting (2**53).
    if (26 + float(weight)) * 14 * scale * weight.denominator >= 2**50:
        raise ValueError('Objective may overflow safe integer reporting; reduce lambda precision or scale')
    return weight.numerator, weight.denominator


def add_value_objective(model, round_values, upper, balance, scale=SCALE):
    numerator, denominator = objective_units(balance, scale)
    highest = model.new_int_var(0, upper, 'U_max')
    lowest = model.new_int_var(0, upper, 'U_min')
    model.add_max_equality(highest, round_values)
    model.add_min_equality(lowest, round_values)
    model.maximize(denominator * sum(round_values) - numerator * (highest - lowest))


def build_model(teams, slots, rules, scenario, balance=3, mode='optimization', scale=SCALE):
    numerator, denominator = objective_units(balance, scale)
    if mode not in ('optimization', 'feasibility'):
        raise ValueError('Unknown search mode')
    model = cp_model.CpModel()
    x, y = {}, {}
    n = len(teams)
    draws = scenario['attractiveness']
    round_values = []
    for r in range(26):
        slot_vars = [[] for _ in slots]
        geo = {}
        objective = []
        for h in range(n):
            for a in range(n):
                if h == a:
                    continue
                x[r, h, a] = model.new_bool_var(f'x_{r}_{h}_{a}')
                choices = []
                for s, slot in enumerate(slots):
                    v = model.new_bool_var(f'y_{r}_{h}_{a}_{s}')
                    y[r, h, a, s] = v
                    choices.append(v)
                    slot_vars[s].append(v)
                    group = teams[h]['home_conflict_group']
                    if group:
                        geo.setdefault((group, slot['day']), []).append(v)
                    coefficient = round((draws[teams[h]['id']][r] + draws[teams[a]['id']][r]) * slot['value'] * scale)
                    objective.append(coefficient * v)
                model.add(sum(choices) == x[r, h, a])
        for t in range(n):
            model.add(sum(x[r, t, a] + x[r, a, t] for a in range(n) if a != t) == 1)
        for values in slot_vars:
            model.add_at_most_one(values)
        for values in geo.values():
            model.add(sum(values) <= 1)
        u = model.new_int_var(0, 14 * scale, f'U_{r}')
        model.add(u == sum(objective))
        round_values.append(u)
    for h, a in combinations(range(n), 2):
        for start in (0, 13):
            model.add(sum(x[r, h, a] + x[r, a, h] for r in range(start, start + 13)) == 1)
        model.add(sum(x[r, h, a] for r in range(26)) == 1)
        model.add(sum(x[r, h, a] + x[r, a, h] for r in (12, 13)) <= 1)
    for t in range(n):
        home = [sum(x[r, t, a] for a in range(n) if a != t) for r in range(26)]
        for r in range(24):
            model.add_linear_constraint(sum(home[r:r + 3]), 1, 2)
    if mode == 'optimization':
        add_value_objective(model, round_values, 14 * scale, balance, scale)
    return model, y
