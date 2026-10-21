"""Configuration and scenario preparation; no solver dependencies."""
import json
import math
import random
from pathlib import Path


def load_inputs(directory):
    root = Path(directory)
    teams, config, rules = [json.loads((root / f'{n}.json').read_text(encoding='utf-8'))
                            for n in ('teams', 'slots', 'rules')]
    teams = sorted(teams, key=lambda t: t['id'])
    slots = sorted(config['slots'], key=lambda s: s['id'])
    expected = dict(rounds=26, rounds_per_half=13, matches_per_round=7,
                    max_consecutive_big_opponents=2,
                    max_home_per_conflict_group_per_day=1,
                    max_consecutive_home=2, max_consecutive_away=2,
                    no_immediate_rematch_between_halves=True)
    if rules != expected:
        raise ValueError('Rules conflict with README')
    if len(teams) != 14 or len({t['id'] for t in teams}) != 14:
        raise ValueError('Expected 14 unique teams')
    if {t['id'] for t in teams} != {'panathinaikos', 'olympiacos', 'aek', 'paok',
            'aris', 'iraklis', 'atromitos', 'kifisia', 'kalamata', 'asteras_tripolis',
            'panetolikos', 'ofi', 'levadiakos', 'volos'}:
        raise ValueError('Team IDs conflict with README')
    protected = {'athens': {'panathinaikos', 'olympiacos', 'aek'},
                 'thessaloniki': {'paok', 'aris', 'iraklis'}}
    for t in teams:
        group = next((g for g, ids in protected.items() if t['id'] in ids), None)
        if t.get('home_conflict_group') != group or 'category' in t:
            raise ValueError('Invalid protected group or obsolete category')
    if [s['id'] for s in slots] != [f'S{i}' for i in range(1, 9)]:
        raise ValueError('Expected S1-S8')
    windows = [('16:00', '17:00'), ('18:00', '19:00'), ('20:00', '21:00'),
               ('16:00', '17:00'), ('17:00', '18:00'), ('18:00', '19:00'), ('20:00', '21:00'),
               ('18:00', '19:00')]
    days = ['saturday'] * 3 + ['sunday'] * 4 + ['monday']
    if config['timezone'] != 'Europe/Athens' or any(
        s['day'] != days[i] or
        (s['start_earliest'], s['start_latest']) != windows[i] or
        not math.isfinite(s['value']) or not 0 < s['value'] <= 1
        for i, s in enumerate(slots)):
        raise ValueError('Invalid slot configuration')
    return teams, slots, rules


def ratings(teams, source, config):
    rows = source['teams']
    if set(rows) != {t['id'] for t in teams}:
        raise ValueError('Rating team IDs must match input teams')
    weights = config['history_weights']
    if len(weights) != 3 or any(not math.isfinite(w) or w < 0 for w in weights) or not math.isclose(sum(weights), 1):
        raise ValueError('Invalid history weights')
    if any(not math.isfinite(config[k]) or config[k] < 0 for k in ('history_factor', 'market_factor')):
        raise ValueError('Invalid rating coefficients')
    result = {}
    for tid in sorted(rows):
        row = rows[tid]
        positions, value = row['positions'], row['market_value_million_eur']
        if len(positions) != 3 or any(type(p) is not int or not 1 <= p <= 15 for p in positions):
            raise ValueError('Positions must be integers 1..15')
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError('Market value must be positive and finite')
        history = sum(w * 100 * (14 - p) / 13 for w, p in zip(weights, positions))
        strength = config['history_factor'] * history + config['market_factor'] * math.log2(value)
        if not math.isfinite(strength):
            raise ValueError('Nonfinite strength')
        result[tid] = {'H': history, 'F': strength}
    lo, hi = min(v['F'] for v in result.values()), max(v['F'] for v in result.values())
    for v in result.values():
        v['mu'] = 0.55 if hi == lo else 0.2 + 0.7 * (v['F'] - lo) / (hi - lo)
    order = sorted(result, key=lambda t: (-result[t]['F'], -rows[t]['market_value_million_eur'], rows[t]['positions'][-1], t))
    return result, order[:4]


def prepare_scenario(teams, source, config, data_seed=0, reuse=None):
    computed, big_four = ratings(teams, source, config)
    rng = random.Random(data_seed)
    values = {tid: [rng.uniform(v['mu'] - 0.1, v['mu'] + 0.1) for _ in range(26)]
              for tid, v in computed.items()} if reuse is None else reuse['attractiveness']
    if set(values) != set(computed):
        raise ValueError('Attractiveness team IDs do not match')
    for tid, draws in values.items():
        mu = computed[tid]['mu']
        if len(draws) != 26 or any(isinstance(a, bool) or not math.isfinite(a) or not mu - .1 - 1e-12 <= a <= mu + .1 + 1e-12 for a in draws):
            raise ValueError('Invalid attractiveness values')
    if reuse is not None and any(reuse.get(k) != v for k, v in
                                 [('source', source), ('rating_config', config), ('ratings', computed), ('big_four', big_four)]):
        raise ValueError('Reused scenario does not match rating inputs')
    return dict(source=source, rating_config=config, ratings=computed, big_four=big_four,
                data_seed=data_seed if reuse is None else reuse['data_seed'], attractiveness=values)
