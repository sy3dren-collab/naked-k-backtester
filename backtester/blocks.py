"""Causal block evaluation: every input is limited to bars completed at `now`."""
from bisect import bisect_right
from collections import deque
from datetime import timedelta, time

from .catalog import CATALOG
from .schema import validate


def extrema(rows, basis='wick'):
    high = max((max(b.open, b.close) if basis == 'body' else b.high) for b in rows)
    low = min((min(b.open, b.close) if basis == 'body' else b.low) for b in rows)
    return {'high': high, 'low': low, 'mid': (high + low) / 2}


def trend(pivots):
    highs = [p['price'] for p in pivots if p['kind'] == 'high'][-2:]
    lows = [p['price'] for p in pivots if p['kind'] == 'low'][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return None
    if highs[1] > highs[0] and lows[1] > lows[0]:
        return 'up'
    if highs[1] < highs[0] and lows[1] < lows[0]:
        return 'down'
    return None


def pivot_updates(bars, count, p, state):
    left, right = p.get('left', 2), p.get('right', 2)
    i = count - 1 - right
    records = state.setdefault('pivots', [])
    fresh = []
    if i < left:
        return records, fresh
    pivot = bars[i]
    before, after = bars[i-left:i], bars[i+1:i+right+1]
    def price(bar, kind):
        return (max(bar.open, bar.close) if kind == 'high' else min(bar.open, bar.close)) if p.get('basis') == 'body' else getattr(bar, kind)
    for kind in ('high', 'low'):
        if p.get('side', 'both') not in ('both', kind):
            continue
        value = price(pivot, kind)
        sign = 1 if kind == 'high' else -1
        ties = p.get('ties', 'strict')
        passes_left = all(sign * (value - price(b, kind)) >= 0 if ties == 'latest' else sign * (value - price(b, kind)) > 0 for b in before)
        passes_right = all(sign * (value - price(b, kind)) >= 0 if ties == 'earliest' else sign * (value - price(b, kind)) > 0 for b in after)
        reaction = min(value - min(b.low for b in before), value - min(b.low for b in after)) if kind == 'high' else min(max(b.high for b in before) - value, max(b.high for b in after) - value)
        if passes_left and passes_right and reaction >= p.get('min_turn', 0):
            record = {'kind': kind, 'price': value, 'candidate_time': pivot.start.isoformat(),
                      'confirmed_at': bars[count-1].end.isoformat(), 'index': i}
            records.append(record); fresh.append(record)
    del records[:-1000]
    return records, fresh


def pattern(kind, current, previous, p, direction):
    up = direction == 'up'
    length = current.high - current.low
    if kind == 'engulfing':
        if previous is None or abs(current.close-current.open) < p.get('min_body', 1):
            return False
        color = current.close > current.open and previous.close < previous.open if up else current.close < current.open and previous.close > previous.open
        if p.get('mode', 'body') == 'full':
            engulf = current.high >= previous.high and current.low <= previous.low
        else:
            engulf = min(current.open, current.close) <= min(previous.open, previous.close) and max(current.open, current.close) >= max(previous.open, previous.close)
        return color and engulf
    if length <= 0 or length < p.get('min_range', 5):
        return False
    wick = min(current.open, current.close)-current.low if up else current.high-max(current.open, current.close)
    close_distance = current.high-current.close if up else current.close-current.low
    return wick/length >= p.get('wick_ratio', .6) and abs(current.close-current.open)/length <= p.get('max_body_ratio', .3) and close_distance/length <= p.get('close_ratio', .25)


class Evaluator:
    def __init__(self, strategy, series):
        self.strategy = strategy
        self.blocks = validate(strategy)
        self.series = series
        self.ends = {tf: [b.end for b in rows] for tf, rows in series.items()}
        self.states, self.values, self.processed = {}, {}, {}

    def active(self, id, stamp):
        value = self.values.get(id)
        return bool(value and value['available'] and value['value'] is True and value['at'].date() == stamp.date() and stamp <= value['valid_until'])

    def step(self, now, context=None):
        context = context or {}
        for block in self.blocks:
            if not block['enabled'] or CATALOG[block['type']]['category'] in ('stop', 'target'):
                continue
            id, kind, tf = block['id'], block['type'], block['timeframe']
            count = bisect_right(self.ends[tf], now)
            if not count or self.processed.get(id) == count:
                continue
            self.processed[id] = count
            bars = self.series[tf]
            b = bars[count-1]
            p = {**{k: v['default'] for k, v in CATALOG[kind]['params'].items()}, **block['params']}
            state = self.states.setdefault(id, {})
            if CATALOG[kind]['category'] not in ('price',) and state.get('day') != b.start.date():
                state.clear(); state['day'] = b.start.date()
            meta, detail, available = {}, '', True
            if CATALOG[kind]['category'] == 'price':
                value, meta = self.price(kind, p, state, bars, count)
                available = value is not None
            else:
                value, detail, available = self.condition(kind, p, state, bars, count, context)
            self.values[id] = {'value': value, 'at': b.end, 'block_id': id, 'available': available,
                               'origin_at': state.get('origin_at', b.end) if kind == 'expire' and value else b.end,
                               'valid_until': b.end + timedelta(minutes=p.get('valid_bars', 1)*tf), 'meta': meta,
                               'reason': f"{block['name']} ({id})：{value}" + (f'；{detail}' if detail else '')}
        return self.values

    def price(self, kind, p, state, bars, count):
        b, tf = bars[count-1], bars[count-1].minutes
        if kind == 'opening_range':
            start_time = time.fromisoformat(p['session_open'])
            anchor = b.start.replace(hour=start_time.hour, minute=start_time.minute)
            end = anchor+timedelta(minutes=p['minutes'])
            if b.end < end:
                return None, {}
            left, right = bisect_right(self.ends[tf], anchor), bisect_right(self.ends[tf], end)
            rows = bars[left:right]
            if rows and len(rows)*tf == p['minutes'] and rows[0].start == anchor and rows[-1].end == end:
                value = extrema(rows); value['value'] = value[p['field']]
                return value, {'formed_at': end.isoformat()}
            return None, {}
        if kind in ('rolling_range', 'ma'):
            end = count if kind == 'ma' else count-1
            rows = bars[max(0, end-p['period']):end]
            if len(rows) != p['period']:
                return None, {}
            if kind == 'ma':
                return {'value': sum(x.close for x in rows)/len(rows)}, {}
            value = extrema(rows, p['basis'])
            if p['lock']:
                if state.get('date') != b.start.date():
                    state.clear(); state['date'] = b.start.date()
                locked = state.get('locked')
                if locked and state.get('broken'):
                    state.pop('locked'); locked = None
                if locked is None:
                    state['locked'] = value; locked = value
                state['broken'] = b.close > locked['high'] or b.close < locked['low']
                value = locked
            return value, {}
        if kind == 'swing':
            pivots, fresh = pivot_updates(bars, count, p, state)
            levels = {}
            for record in reversed(pivots):
                levels.setdefault(record['kind'], record['price'])
                if len(levels) == 2: break
            if 'high' in levels and 'low' in levels:
                levels['mid'] = (levels['high']+levels['low'])/2
            return levels or None, {'pivots': pivots[-20:], 'new_pivots': fresh, 'trend': trend(pivots[-20:])}
        if kind in ('previous_day', 'day_range', 'gap'):
            if state.get('date') != b.start.date():
                if 'today' in state:
                    state['previous'] = state['today']
                state['date'] = b.start.date()
                state['today'] = {'open': b.open, 'high': b.high, 'low': b.low, 'close': b.close}
                state['gap_open'] = b.open
            else:
                today = state['today']
                today['high'] = max(today['high'], b.high); today['low'] = min(today['low'], b.low); today['close'] = b.close
            if kind == 'previous_day':
                return state.get('previous'), {}
            if kind == 'day_range':
                return dict(state['today']), {}
            previous = state.get('previous')
            if not previous:
                return None, {}
            opening, close = state['gap_open'], previous['close']
            direction = 'up' if opening > close else 'down'
            if abs(opening-close) < p['min_gap'] or p['direction'] not in ('both', direction) or opening == close:
                return None, {}
            today = state['today']
            fill = (opening-today['low'])/(opening-close) if direction == 'up' else (today['high']-opening)/(close-opening)
            return {'high': max(opening, close), 'low': min(opening, close), 'mid': (opening+close)/2}, {'direction': direction, 'fill_ratio': max(0, min(1, fill))}
        if kind == 'snapshot':
            if state.get('date') != b.start.date():
                state.clear(); state['date'] = b.start.date()
            trigger, source = self.values.get(p['trigger']), self.values.get(p['source'])
            if self.active(p['trigger'], b.end) and trigger['at'] == b.end and source and source['value']:
                state['level'] = dict(source['value']); state['locked_at'] = b.end.isoformat()
            return state.get('level'), {'locked_at': state.get('locked_at')}
        if kind == 'box':
            rows = bars[max(0, count-1-p['period']):count-1]
            if len(rows) != p['period']:
                return None, {}
            if state.get('broken'):
                state.clear()
            candidate = extrema(rows)
            if not p['min_width'] <= candidate['high']-candidate['low'] <= p['max_width']:
                state.clear(); return None, {}
            if 'level' not in state:
                previous = state.get('candidate')
                stable = previous and abs(previous['high']-candidate['high']) <= p['tolerance'] and abs(previous['low']-candidate['low']) <= p['tolerance']
                state['held'] = state.get('held', 0)+1 if stable else 1
                state['candidate'] = candidate
                if state['held'] >= p['hold']:
                    state['level'] = candidate; state['formed_at'] = b.end.isoformat()
            value = state.get('level')
            if value:
                state['broken'] = b.close > value['high'] or b.close < value['low']
            return value, {'formed_at': state.get('formed_at'), 'held': state.get('held', 0), 'broken': state.get('broken', False)}
        if kind == 'support_resistance':
            zones = state.setdefault('zones', [])
            if p['method'] == 'swing':
                _, fresh = pivot_updates(bars, count, {'left': p['left'], 'right': p['right'], 'min_turn': p['reaction']}, state)
                candidates = [(x['price'], 'resistance' if x['kind'] == 'high' else 'support') for x in fresh]
            else:
                rows = bars[max(0, count-1-p['period']):count-1]
                candidates = []
                if len(rows) == p['period']:
                    level = extrema(rows)
                    candidates = [(level['high'], 'resistance'), (level['low'], 'support')]
            for value, role in candidates:
                match = next((z for z in zones if abs(z['center']-value) <= p['tolerance']), None)
                if match is None:
                    half = p['tolerance'] if p['mode'] == 'zone' else 0
                    state['zone_serial'] = state.get('zone_serial', 0)+1
                    zones.append({'id': state['zone_serial'], 'center': value, 'high': value+half, 'low': value-half,
                                  'role': role, 'tests': 1 if p['method'] == 'swing' else 0, 'created_at': b.end.isoformat(),
                                  'left': True, 'touching': False, 'broken_at': None})
                elif p['method'] == 'swing' and match.get('last_pivot_at') != b.end.isoformat():
                    # Subsequent pivot confirmation may describe a touch already counted.
                    # Independent tests are counted exclusively by leave / return / reaction.
                    match['last_pivot_at'] = b.end.isoformat()
            for zone in zones:
                if zone['created_at'] == b.end.isoformat() or zone.get('last_pivot_at') == b.end.isoformat():
                    continue
                touches = b.low <= zone['high'] and b.high >= zone['low']
                away = b.close >= zone['high']+p['reaction'] if zone['role'] == 'support' else b.close <= zone['low']-p['reaction']
                if touches and zone['left']:
                    zone['touching'] = True; zone['left'] = False; zone['touch_at'] = b.end.isoformat()
                if zone['touching'] and away and b.end.isoformat() > zone.get('touch_at', ''):
                    zone['tests'] += 1; zone['touching'] = False; zone['left'] = True
                elif not touches and away:
                    zone['left'] = True
                broken = b.close < zone['low']-p['reaction'] if zone['role'] == 'support' else b.close > zone['high']+p['reaction']
                if broken and (not zone.get('broken_at') or p['role_reversal']):
                    zone['broken_at'] = b.end.isoformat()
                    if p['role_reversal']:
                        zone['role'] = 'resistance' if zone['role'] == 'support' else 'support'
                        zone['left'] = True
            del zones[:-p['max_zones']]
            for zone in zones:
                if zone['tests'] >= p['min_tests'] and not zone.get('confirmed_at'):
                    zone['confirmed_at'] = b.end.isoformat()
            usable = [z for z in zones if z['tests'] >= p['min_tests'] and p['role'] in ('both', z['role']) and (p['role_reversal'] or not z['broken_at'])]
            selected = min(usable, key=lambda z: abs(z['center']-b.close)) if usable else None
            return ({k: selected[k] for k in ('high', 'low')} | {'mid': selected['center']} if selected else None), {'zones': [dict(z) for z in zones], 'min_tests': p['min_tests']}
        raise ValueError('未實作的價格積木：'+kind)

    def condition(self, kind, p, state, bars, count, context):
        b = bars[count-1]
        previous = bars[count-2] if count > 1 else None
        source = self.values.get(p.get('source'))
        ref = source['value'] if source and isinstance(source['value'], dict) else None
        meta = source.get('meta', {}) if source else {}
        position = context.get('position')
        up = p.get('direction', 'up') == 'up'
        level = ref.get(p.get('field', 'high' if up else 'low')) if ref else None
        available = True
        truth, detail = False, ''
        if kind in ('and', 'or', 'not', 'sequence', 'count', 'expire', 'reset', 'delay', 'event', 'occurrence_filter'):
            def active(id): return self.active(id, b.end)
            if kind in ('and', 'or'):
                flags = [active(id) for id in p['inputs']]
                truth = all(flags) if kind == 'and' else any(flags)
                detail = ', '.join(f'{id}={flag}' for id, flag in zip(p['inputs'], flags))
            elif kind == 'not':
                available = bool(source and source['available'])
                truth = available and not active(p['source'])
            elif kind == 'sequence':
                ids = p['inputs']; cursor = state.get('cursor', 0); last = state.get('last')
                if last and (b.end-state.get('started', last)).total_seconds() > p['within']*60:
                    cursor = 0; last = None
                a = self.values.get(ids[0])
                if active(ids[0]) and state.get('a') != a['at'] and (cursor == 0 or p['restart_on_a']):
                    cursor = 1; last = a['at']; state['a'] = last; state['started'] = last; state['times'] = [last.isoformat()]
                elif cursor and cursor < len(ids) and active(ids[cursor]):
                    signal = self.values[ids[cursor]]
                    if signal['at'] > last:
                        last = signal['at']; cursor += 1; state['times'].append(last.isoformat())
                        if cursor == len(ids):
                            truth = True; detail = ' → '.join(state['times']); cursor = 0
                state['cursor'], state['last'] = cursor, last
            else:
                signal = self.values.get(p['source']); fresh = bool(active(p['source']) and state.get('used') != signal['at'])
                if fresh:
                    state['used'] = signal['at']
                if kind == 'event':
                    truth = active(p['source']) and not state.get('active', False)
                    state['active'] = active(p['source'])
                elif kind in ('count', 'occurrence_filter'):
                    if kind == 'occurrence_filter':
                        if fresh: state['count'] = state.get('count', 0)+1
                        truth = fresh and state.get('count') == p['occurrence']
                    else:
                        hits = state.setdefault('hits', deque())
                        if fresh: hits.append(count)
                        while hits and hits[0] <= count-p['window']: hits.popleft()
                        truth = len(hits) >= p['count']
                elif kind == 'expire':
                    if fresh: state['expires'] = count+p['bars']; state['origin_at'] = signal.get('origin_at', signal['at'])
                    truth = count < state.get('expires', 0)
                elif kind == 'reset':
                    if fresh: state['latched'] = True
                    if active(p['reset']): state['latched'] = False
                    truth = state.get('latched', False)
                elif kind == 'delay':
                    due = state.setdefault('due', set())
                    if fresh: due.add(count+p['bars'])
                    truth = count in due
                    due.difference_update(x for x in list(due) if x <= count)
        elif kind in ('breakout', 'compare', 'bos', 'box_break'):
            waiting = state.get('retest') if kind == 'box_break' else None
            if waiting:
                if count > waiting['expires']:
                    state.pop('retest')
                else:
                    edge = waiting['level']
                    touched = b.low <= edge+p['tolerance'] and b.high >= edge-p['tolerance']
                    truth = count > waiting['at'] and touched and (b.close > edge if up else b.close < edge)
                    if truth: state.pop('retest')
                    return truth, f'鎖定箱體邊界={edge}，突破後回踩', True
            if kind in ('bos', 'box_break'):
                level = ref.get('high' if up else 'low') if ref else None
            available = level is not None
            if available:
                if state.get('armed') and kind not in ('compare',):
                    level = state['reference']
                mode = p.get('mode', 'close'); buffer = p.get('min_break', 0)
                observed = (b.high if up else b.low) if mode in ('touch', 'cross') else (min(b.open, b.close) if up else max(b.open, b.close)) if mode == 'body' else b.close
                beyond = (observed >= level+buffer if up else observed <= level-buffer) if mode == 'touch' else (observed > level+buffer if up else observed < level-buffer)
                formed = meta.get('formed_at')
                if mode in ('touch', 'cross') and formed and formed > b.start.isoformat():
                    beyond = False
                if kind == 'compare':
                    truth = beyond
                else:
                    if not state.get('armed') and state.get('reference') != level:
                        state['streak'] = 0; state['reference'] = level
                    state['streak'] = state.get('streak', 0)+1 if beyond else 0
                    prior_price = (min(previous.open, previous.close) if up else max(previous.open, previous.close)) if previous and mode == 'body' else previous.close if previous else None
                    crossed = previous and (prior_price <= level+buffer if up else prior_price >= level-buffer)
                    if crossed and beyond:
                        state['armed'] = True
                    if not beyond:
                        state['armed'] = False
                    if state.get('armed') and state['streak'] >= p.get('confirm', 1):
                        state['armed'] = False; state['occurrences'] = state.get('occurrences', 0)+1
                        truth = not p.get('occurrence') or state['occurrences'] == p['occurrence']
                    if p.get('max_chase') and abs(b.close-level) > p['max_chase']:
                        truth = False
                    if kind == 'bos' and p['require_trend'] and meta.get('trend') != p['direction']:
                        truth = False
                    if kind == 'box_break' and p['wait_retest']:
                        if truth: state['retest'] = {'level': level, 'expires': count+p['within'], 'at': count}
                        truth = False
                detail = f'已完成 K 收盤={b.close}，參考={level}，方式={mode}'
        elif kind == 'touch_reference':
            available = level is not None
            truth = available and b.low <= level+p['tolerance'] and b.high >= level-p['tolerance'] and (b.close > level if up else b.close < level)
        elif kind == 'retest':
            available = level is not None
            waiting = state.get('waiting')
            if waiting and (count > waiting['expires'] or (b.close < waiting['level']-p['invalidation'] if up else b.close > waiting['level']+p['invalidation'])):
                state.pop('waiting'); waiting = None
            if waiting:
                locked = waiting['level']
                touched = b.low <= locked+p['tolerance'] and b.high >= locked-p['tolerance'] if p['mode'] == 'wick' else abs(b.close-locked) <= p['tolerance']
                if not touched: waiting['left'] = True
                if touched and waiting['left']:
                    waiting['touches'] += 1; waiting['left'] = False
                color = b.close > b.open if up else b.close < b.open
                if touched and waiting['touches'] == p['occurrence'] and (p['confirm'] == 'none' or color):
                    if p['confirm'] == 'break_candle': waiting.setdefault('confirm', b)
                    else: truth = True
                confirm = waiting.get('confirm')
                if confirm and b.start > confirm.start and (b.close > confirm.high if up else b.close < confirm.low): truth = True
                if truth: state.pop('waiting')
                detail = f"鎖定參考={locked}，回踩次數={waiting['touches']}"
            if not waiting and available and previous and (previous.close <= level < b.close if up else previous.close >= level > b.close):
                state['waiting'] = {'level': level, 'expires': count+p['within'], 'touches': 0, 'left': True}
        elif kind in ('bounce', 'rejection'):
            up = p['direction'] == 'up'; edge = ref.get('low' if up else 'high') if ref else None; available = edge is not None
            pending = state.get('confirm')
            if pending and count <= pending['expires'] and b.start > pending['bar'].start and (b.close > pending['bar'].high if up else b.close < pending['bar'].low):
                truth = True; state.pop('confirm')
            length = b.high-b.low; wick = min(b.open, b.close)-b.low if up else b.high-max(b.open, b.close)
            touch = available and b.low <= edge+p['tolerance'] and b.high >= edge-p['tolerance']
            reaction = b.close-b.low if up else b.high-b.close
            if touch and length > 0 and wick/length >= p['wick_ratio'] and reaction >= p['reaction'] and (b.close > b.open if up else b.close < b.open):
                if p['confirm_break']: state['confirm'] = {'bar': b, 'expires': count+p['within']}
                else: truth = True
            detail = f'已知區邊界={edge}，影線={wick}，反應={reaction}'
        elif kind == 'false_break':
            available = level is not None
            if available and ((b.high > level+p['min_break']) if up else (b.low < level-p['min_break'])) and 'break' not in state:
                state['break'] = {'level': level, 'expires': count+p['within']}
            broken = state.get('break')
            if broken:
                if count > broken['expires']: state.pop('break')
                elif (b.close < broken['level'] if up else b.close > broken['level']) and (not p['reverse_candle'] or (b.close < b.open if up else b.close > b.open)):
                    truth = True; detail = f"突破後收回 {broken['level']}"; state.pop('break')
        elif kind in ('n_pattern', 'pullback_filter'):
            pivots = meta.get('pivots', [])
            kinds = ('low', 'high', 'low') if up else ('high', 'low', 'high')
            zigzag = []
            for point in pivots:
                if zigzag and zigzag[-1]['kind'] == point['kind']:
                    if point['price'] > zigzag[-1]['price'] if point['kind'] == 'high' else point['price'] < zigzag[-1]['price']: zigzag[-1] = point
                else: zigzag.append(point)
            available = len(zigzag) >= 3
            if available:
                a, h, c = zigzag[-3:]; sign = 1 if up else -1
                signature = tuple(x['candidate_time'] for x in (a,h,c))
                if state.get('pattern') != signature:
                    state['pattern'] = signature; state['invalid'] = False
                if (b.close-c['price'])*sign < 0: state['invalid'] = True
                push = sign*(h['price']-a['price']); depth = sign*(h['price']-c['price'])/push if push > 0 else -1
                if tuple(x['kind'] for x in (a, h, c)) == kinds and sign*(c['price']-a['price']) > 0:
                    if kind == 'pullback_filter': truth = p['minimum'] <= depth <= p['maximum']
                    else:
                        truth = not state['invalid'] and push >= p['min_push'] and p['min_retrace'] <= depth <= p['max_retrace'] and count-1-h['index'] <= p['max_pullback'] and previous is not None and (previous.close <= h['price']+p['min_break'] < b.close if up else previous.close >= h['price']-p['min_break'] > b.close)
                    detail = f'推進={push}，回調比例={depth}，結構停損={c["price"]}'
        elif kind == 'choch':
            current_trend = meta.get('trend'); old = state.get('trend')
            edge = ref.get('high' if up else 'low') if ref else None; available = edge is not None
            broken = available and old == ('down' if up else 'up') and (b.close > edge+p['min_break'] if up else b.close < edge-p['min_break'])
            if broken:
                if p['wait_retest']: state['pending'] = {'level': edge, 'at': count, 'expires': count+p['within']}
                else: truth = True
            pending = state.get('pending')
            if pending and (count > pending['expires'] or (b.close < pending['level']-p['tolerance'] if up else b.close > pending['level']+p['tolerance'])):
                state.pop('pending'); pending = None
            if pending and count > pending['at'] and count <= pending['expires'] and b.low <= pending['level']+p['tolerance'] and b.high >= pending['level']-p['tolerance'] and (b.close > pending['level'] if up else b.close < pending['level']):
                truth = True; state.pop('pending')
            if current_trend: state['trend'] = current_trend
        elif kind in ('engulfing', 'pinbar', 'candle', 'consecutive'):
            if kind == 'candle': truth = b.close > b.open if up else b.close < b.open
            elif kind == 'consecutive':
                rows = bars[max(0, count-p['count']):count]
                truth = len(rows) == p['count'] and all((x.close > x.open if up else x.close < x.open) and abs(x.close-x.open) >= p['min_body'] for x in rows) and (rows[-1].close-rows[0].open)*(1 if up else -1) >= p['min_push']
                if truth and p['staircase']: truth = all(c.high > a.high if up else c.low < a.low for a, c in zip(rows, rows[1:]))
                if truth and p['higher_highs']: truth = all(c.high > a.high for a,c in zip(rows,rows[1:]))
                if truth and p['lower_lows']: truth = all(c.low < a.low for a,c in zip(rows,rows[1:]))
            else:
                pending = state.get('confirm')
                if pending and count <= pending['expires'] and b.start > pending['bar'].start and (b.close > pending['bar'].high if up else b.close < pending['bar'].low): truth = True; state.pop('confirm')
                valid = pattern(kind, b, previous, p, p['direction'])
                if valid:
                    if p.get('confirm_break'): state['confirm'] = {'bar': b, 'expires': count+p['within']}
                    else: truth = True
            detail = f'開盤={b.open}，收盤={b.close}'
        elif kind == 'time_filter': truth = p['start'] <= b.end.strftime('%H:%M') < p['end']
        elif kind == 'trend_filter': available = bool(meta.get('trend')); truth = meta.get('trend') == p['direction']
        elif kind in ('range_filter', 'distance_filter', 'risk_distance_filter', 'space_filter'):
            available = ref is not None
            if available:
                if kind == 'range_filter': available = 'high' in ref and 'low' in ref; distance = ref['high']-ref['low'] if available else 0
                elif kind == 'distance_filter': available = level is not None; distance = abs(b.close-level) if available else 0
                elif kind == 'risk_distance_filter': edge = ref.get('low' if up else 'high'); available = edge is not None; distance = (b.close-edge)*(1 if up else -1) if available else -1
                else: edge = ref.get('high' if up else 'low'); available = edge is not None; distance = (edge-b.close)*(1 if up else -1) if available else -1
                truth = available and p.get('minimum', 0) <= distance <= p.get('maximum', float('inf'))
                detail = f'距離／寬度={distance}'
        elif kind == 'body_filter': truth = p['minimum'] <= abs(b.close-b.open) <= p['maximum']
        elif kind == 'cooldown_filter': truth = context.get('since_stop', float('inf')) >= p['bars']*b.minutes
        elif kind == 'daily_count_filter': truth = context.get('daily_trades', 0) < p['maximum']
        elif kind == 'calendar_filter': truth = b.start.weekday() not in p['weekdays'] and b.start.date().isoformat() not in p['dates']
        elif kind.startswith('exit_'):
            available = position is not None
            if position:
                d = position['direction']; up = d == 1
                if kind in ('exit_structure', 'exit_n_failure'):
                    reference = position.get('reference_at_entry', {}).get(p['source'], {}) if kind == 'exit_n_failure' else ref
                    edge = reference.get('low' if up else 'high') if reference else None
                    truth = edge is not None and (b.close < edge if up else b.close > edge)
                elif kind == 'exit_failure':
                    edge = position.get('break_level')
                    original = position.get('reference_at_entry', {}).get(p['source'], {})
                    if edge is None and original: edge = original.get('high' if up else 'low')
                    truth = edge is not None and (b.close < edge-p['tolerance'] if up else b.close > edge+p['tolerance'])
                elif kind == 'exit_reversal': truth = pattern(p['pattern'], b, previous, {}, 'down' if up else 'up')
                elif kind == 'exit_ma':
                    rows = bars[max(0, count-p['period']):count]
                    if len(rows) == p['period']:
                        average = sum(x.close for x in rows)/len(rows)
                        observed = max(b.open, b.close) if up else min(b.open, b.close) if p['mode'] == 'body' else b.close
                        if p['mode'] == 'close': observed = b.close
                        truth = observed < average if up else observed > average
                elif kind == 'exit_bars': truth = b.end-position['entry_time'] >= timedelta(minutes=p['bars']*b.minutes)
                elif kind == 'exit_time': truth = b.end.strftime('%H:%M') >= p['time']
                elif kind == 'exit_giveback':
                    best = position.get('best_points', 0); current = (b.close-position['entry_price'])*d
                    truth = best >= p['activate'] and best > 0 and (best-current)/best >= p['percent']
                elif kind == 'exit_consecutive':
                    rows = bars[max(0, count-p['count']):count]
                    truth = len(rows) == p['count'] and all(x.close < x.open if up else x.close > x.open for x in rows)
                detail = f'持倉方向={position["side"]}，當前收盤={b.close}'
        else:
            raise ValueError('未實作的條件積木：'+kind)
        return bool(truth), detail, available
