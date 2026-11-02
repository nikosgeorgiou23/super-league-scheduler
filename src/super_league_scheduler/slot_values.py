"""Historical slot scores and sigmoid weights; no solver dependencies."""
import csv
import hashlib
import math
from pathlib import Path

SIGMOID_SLOPE = 0.065
DAY_NAMES = {'Δευτέρα': 'monday', 'Τρίτη': 'tuesday', 'Τετάρτη': 'wednesday',
             'Πέμπτη': 'thursday', 'Παρασκευή': 'friday', 'Σάββατο': 'saturday',
             'Κυριακή': 'sunday'}


def clock_minutes(value):
    """Parse a clock time, allowing 24:00 only as a window endpoint."""
    if not isinstance(value, str) or len(value) != 5 or value[2] != ':':
        raise ValueError(f'Invalid clock time: {value!r}')
    try:
        hour, minute = map(int, value.split(':'))
    except ValueError as exc:
        raise ValueError(f'Invalid clock time: {value!r}') from exc
    if not (0 <= hour <= 24 and 0 <= minute < 60 and (hour < 24 or minute == 0)):
        raise ValueError(f'Invalid clock time: {value!r}')
    return hour * 60 + minute


def load_historical_scores(path):
    """Read the existing historical-analysis CSV without recomputing team ratings.

    mean_strength is the previously computed sum(F_home+F_away)/match_count.
    Missing/zero observations and invalid scores fail explicitly; no fallback.
    """
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if set(reader.fieldnames or ()) != {'day', 'window', 'mean_strength', 'match_count'}:
            raise ValueError('Historical CSV requires day, window, mean_strength, match_count')
        records = []
        seen = set()
        for row in reader:
            day = DAY_NAMES.get(row['day'], row['day'])
            if day not in DAY_NAMES.values():
                raise ValueError(f'Invalid historical weekday: {day}')
            window = row['window'].split('–')
            if len(window) != 2:
                raise ValueError(f'Invalid historical window: {row["window"]}')
            start, end = window
            if clock_minutes(start) >= clock_minutes(end):
                raise ValueError('Historical window must have increasing endpoints (use 24:00 for midnight)')
            slot_id = f'{day}_{start.replace(":", "")}_{end.replace(":", "")}'
            if slot_id in seen:
                raise ValueError(f'Duplicate historical slot: {slot_id}')
            seen.add(slot_id)
            try:
                observations = int(row['match_count'])
                score = float(row['mean_strength'])
            except (TypeError, ValueError) as exc:
                raise ValueError(f'Invalid historical observations/score for {slot_id}') from exc
            if observations <= 0:
                raise ValueError(f'No historical observations for {slot_id}')
            if not math.isfinite(score) or score <= 0:
                raise ValueError(f'Invalid historical score for {slot_id}')
            records.append(dict(id=slot_id, day=day, start=start, end=end,
                                score=score, observations=observations))
    if not records:
        raise ValueError('No historical slot scores available')
    return records


def sigmoid_weights(scores):
    """Normalize the complete available score catalog before mapping model slots."""
    scores = list(scores)
    if not scores or any(isinstance(d, bool) or not math.isfinite(d) for d in scores):
        raise ValueError('Historical scores must be a nonempty finite sequence')
    minimum, maximum = min(scores), max(scores)
    center = minimum / 2 + maximum / 2
    values = []
    for score in scores:
        z = SIGMOID_SLOPE * (score - center)
        if z >= 0:
            value = 1 / (1 + math.exp(-z))
        else:
            e = math.exp(z)
            value = e / (1 + e)
        # Do not clip saturated values or invent a replacement observation.
        if not 0 < value < 1:
            raise ValueError('Sigmoid weight saturated outside the strict (0,1) interval')
        values.append(value)
    return center, values


def value_slots(slots, historical_path):
    """Attach one authoritative normalized weight to each unchanged model slot."""
    history = load_historical_scores(historical_path)
    center, weights = sigmoid_weights(row['score'] for row in history)
    by_id = {row['id']: (row, weight) for row, weight in zip(history, weights)}
    source_hash = hashlib.sha256(Path(historical_path).read_bytes()).hexdigest()
    minimum = min(row['score'] for row in history)
    maximum = max(row['score'] for row in history)
    valued = []
    for slot in slots:
        if 'value' in slot:
            raise ValueError(f'Hardcoded slot value is obsolete: {slot.get("id")}')
        key = slot.get('historical_slot')
        if key not in by_id:
            raise ValueError(f'Missing historical observations/mapping for {slot.get("id")}: {key}')
        row, weight = by_id[key]
        if (slot['day'] != row['day'] or
                not clock_minutes(row['start']) <= clock_minutes(slot['start_earliest']) <=
                clock_minutes(slot['start_latest']) <= clock_minutes(row['end'])):
            raise ValueError(f'Historical mapping does not contain model slot {slot["id"]}')
        valued.append(dict(slot, value=weight, historical_score=row['score'],
                           historical_observations=row['observations'],
                           historical_start=row['start'], historical_end=row['end'],
                           normalization_slope=SIGMOID_SLOPE, normalization_center=center,
                           historical_minimum=minimum, historical_maximum=maximum,
                           historical_catalog_size=len(history), historical_source_sha256=source_hash))
    return valued


def valuation_report(slots):
    """Use already normalized inputs for reporting; do not recalculate weights."""
    first = slots[0]
    return dict(method='sigmoid', slope=first['normalization_slope'],
                center=first['normalization_center'], historical_minimum=first['historical_minimum'],
                historical_maximum=first['historical_maximum'],
                historical_catalog_size=first['historical_catalog_size'],
                historical_source_sha256=first['historical_source_sha256'], slots=slots)
