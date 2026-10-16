"""Full feasibility model without an objective or fixed round-robin template."""
from itertools import combinations
from ortools.sat.python import cp_model
from .data import derby_kind


def build_model(teams, slots, rules):
    model = cp_model.CpModel()
    x, y = {}, {}
    n = len(teams)
    for r in range(26):
        slot_vars = [[] for _ in slots]
        geo = {}
        for h in range(n):
            for a in range(n):
                if h == a:
                    continue
                x[r, h, a] = model.new_bool_var(f'x_{r}_{h}_{a}')
                choices = []
                for s, slot in enumerate(slots):
                    if ('big' in (teams[h]['category'], teams[a]['category'])
                            and slot['id'] not in rules['big_team_allowed_slots']):
                        continue
                    v = model.new_bool_var(f'y_{r}_{h}_{a}_{s}')
                    y[r, h, a, s] = v
                    choices.append(v)
                    slot_vars[s].append(v)
                    group = teams[h]['home_conflict_group']
                    if group:
                        geo.setdefault((group, slot['day']), []).append(v)
                model.add(sum(choices) == x[r, h, a])
        for t in range(n):
            model.add(sum(x[r, t, a] + x[r, a, t] for a in range(n) if a != t) == 1)
        for values in slot_vars:
            model.add_exactly_one(values)
        for values in geo.values():
            model.add(sum(values) <= rules['max_home_per_conflict_group_per_day'])
        # Count individual big-team appearances on Saturday, not just matches.
        model.add(sum(v * ((teams[h]['category'] == 'big') +
                           (teams[a]['category'] == 'big'))
                      for (rr, h, a, s), v in y.items()
                      if rr == r and slots[s]['day'] == 'saturday')
                  <= rules['max_big_teams_saturday'])
        if rules['derby_slot_rules_enabled']:
            _add_derby_slots(model, r, x, y, teams, slots)
        model.add(sum(x[r, h, a] for h in range(n) for a in range(n)
                      if h != a and derby_kind(teams[h], teams[a]))
                  <= (0 if r + 1 in rules['no_derby_rounds'] else rules['max_derbies_per_round']))
    for h, a in combinations(range(n), 2):
        for start in (0, 13):
            model.add(sum(x[r, h, a] + x[r, a, h] for r in range(start, start + 13)) == 1)
        model.add(sum(x[r, h, a] for r in range(26)) == 1)
        first = sum((r + 1) * (x[r, h, a] + x[r, a, h]) for r in range(13))
        second = sum((r + 1) * (x[r, h, a] + x[r, a, h]) for r in range(13, 26))
        model.add(second - first >= rules['min_rematch_round_difference'])
    for t in range(n):
        home = [sum(x[r, t, a] for a in range(n) if a != t) for r in range(26)]
        big_opponents = [sum(x[r, t, a] + x[r, a, t]
                             for a in range(n) if a != t and teams[a]['category'] == 'big')
                         for r in range(26)]
        for r in range(24):
            model.add_linear_constraint(sum(home[r:r + 3]), 1, 2)
            model.add(sum(big_opponents[r:r + 3]) <= rules['max_consecutive_big_opponents'])
    return model, y


def _add_derby_slots(model, r, x, y, teams, slots):
    """Enforce the exhaustive round-level derby cases with reified counts."""
    pairs = [(h, a) for h in range(len(teams)) for a in range(len(teams))
             if h != a and derby_kind(teams[h], teams[a])]
    big_count = sum(x[r, h, a] for h, a in pairs
                    if derby_kind(teams[h], teams[a]) == 'big')
    small_count = sum(x[r, h, a] for h, a in pairs
                      if derby_kind(teams[h], teams[a]) == 'small')
    cases = {}
    for big, small in ((0, 0), (0, 1), (1, 0), (0, 2), (2, 0), (1, 1)):
        flag = model.new_bool_var(f'derby_case_{r}_{big}_{small}')
        model.add(big_count == big).only_enforce_if(flag)
        model.add(small_count == small).only_enforce_if(flag)
        cases[big, small] = flag
    model.add_exactly_one(list(cases.values()))
    for (rr, h, a, s), var in y.items():
        if rr != r or (h, a) not in pairs:
            continue
        kind = derby_kind(teams[h], teams[a])
        balander_pair = teams[h]['category'] == teams[a]['category'] == 'balander'
        for (big, small), flag in cases.items():
            if (big, small) == (0, 0):
                continue
            if big + small == 1:
                allowed = {'S3'} if balander_pair else {'S7'}
            elif big == 2 or small == 2:
                allowed = {'S6', 'S7'}
            elif kind == 'big':
                allowed = {'S7'}
            else:
                allowed = {'S3'} if balander_pair else {'S6'}
            if slots[s]['id'] not in allowed:
                model.add(var == 0).only_enforce_if(flag)
