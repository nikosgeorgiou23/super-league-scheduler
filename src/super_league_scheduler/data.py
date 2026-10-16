"""Read configuration independently of OR-Tools."""
import json
from pathlib import Path


def load_inputs(directory):
    teams, config, rules = [json.loads((Path(directory) / f'{n}.json').read_text(encoding='utf-8'))
                            for n in ('teams', 'slots', 'rules')]
    slots = sorted(config['slots'], key=lambda s: s['id'])
    expected = dict(rounds=26, rounds_per_half=13, matches_per_round=7,
                    max_derbies_per_round=2, no_derby_rounds=[1, 2],
                    max_consecutive_home=2, max_consecutive_away=2,
                    max_consecutive_big_opponents=2,
                    min_rematch_round_difference=3, mirror_required=False,
                    mirror_forbidden=False, derby_slot_rules_enabled=True,
                    max_big_teams_saturday=1,
                    max_home_per_conflict_group_per_day=1)
    for k, v in expected.items():
        if rules.get(k) != v:
            raise ValueError(f'{k} conflicts with README; expected {v!r}')
    if len(teams) != 14 or len({t['id'] for t in teams}) != 14:
        raise ValueError('Expected 14 unique teams')
    if any(t['category'] not in {'big', 'balander', 'other'} for t in teams):
        raise ValueError('Unknown category')
    big = {'panathinaikos', 'olympiacos', 'aek', 'paok'}
    balander = {'aris', 'iraklis'}
    athens = {'panathinaikos', 'olympiacos', 'aek'}
    thessaloniki = {'paok', 'aris', 'iraklis'}
    other = {'atromitos', 'kifisia', 'kalamata', 'asteras_tripolis',
             'panetolikos', 'ofi', 'levadiakos', 'volos'}
    if {t['id'] for t in teams} != big | balander | other:
        raise ValueError('Team IDs conflict with README')
    for t in teams:
        category = 'big' if t['id'] in big else 'balander' if t['id'] in balander else 'other'
        group = 'athens' if t['id'] in athens else 'thessaloniki' if t['id'] in thessaloniki else None
        if t['category'] != category or t['home_conflict_group'] != group:
            raise ValueError(f"Category or protected group conflicts with README: {t['id']}")
    if len(slots) != 7 or [s['id'] for s in slots] != [f'S{i}' for i in range(1, 8)]:
        raise ValueError('Expected S1–S7')
    if any(s['day'] != ('saturday' if i < 3 else 'sunday') for i, s in enumerate(slots)):
        raise ValueError('Slot days conflict with README')
    windows = [('16:00', '17:00'), ('18:00', '19:00'), ('20:00', '21:00'),
               ('16:00', '17:00'), ('17:00', '18:00'), ('18:00', '19:00'), ('20:00', '21:00')]
    if config['timezone'] != 'Europe/Athens' or any(
            (s['start_earliest'], s['start_latest']) != w for s, w in zip(slots, windows)):
        raise ValueError('Time windows or timezone conflict with README')
    if set(rules['big_team_allowed_slots']) != {'S3', 'S4', 'S6', 'S7'}:
        raise ValueError('Big team slots conflict with README')
    return teams, slots, rules


def derby_kind(a, b):
    if 'other' in (a['category'], b['category']):
        return None
    return 'big' if a['category'] == b['category'] == 'big' else 'small'
