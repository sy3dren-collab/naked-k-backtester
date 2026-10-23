"""Typed block graph. Evaluators receive completed bars only."""
from bisect import bisect_right
from datetime import timedelta
import math
import copy

PRICE = {'opening_range', 'rolling_range', 'swing', 'ma', 'snapshot'}
CONDITION = {'breakout', 'retest', 'candle', 'compare', 'and', 'or', 'sequence'}
TYPES = PRICE | CONDITION | {'event'}


def version_identity(strategy):
    """Compare effective content without changing the originally saved document."""
    normalized = copy.deepcopy(strategy)
    normalized['version'] = str(normalized['version'])
    for key in ('stop_points', 'target_points', 'structure_source'):
        if normalized['risk'].get(key) is None:
            normalized['risk'].pop(key, None)
    return normalized


def dependencies(block):
    p = block['params']
    if block['type'] in ('breakout', 'retest', 'compare'):
        return [p.get('source')]
    if block['type'] in ('and', 'or', 'sequence'):
        return p.get('inputs', [])
    if block['type'] == 'event':
        return [p.get('source')]
    if block['type'] == 'snapshot':
        return [p.get('source'), p.get('trigger')]
    return []


def validate(strategy):
    if isinstance(strategy, dict) and strategy.get('schema_version') == 2:
        from .schema import validate as validate_extended
        return validate_extended(strategy)
    if not isinstance(strategy, dict):
        raise ValueError('策略必須是 JSON 物件')
    for key in ('strategy_id', 'version', 'instrument', 'timeframe', 'blocks', 'entries', 'exits', 'risk', 'limits', 'execution', 'costs'):
        if key not in strategy:
            raise ValueError(f'策略缺少 {key}')
    if not strategy['strategy_id'] or not str(strategy['version']):
        raise ValueError('策略 ID 與版本不可空白')
    if strategy['timeframe'] not in (1, 5, 15):
        raise ValueError('策略週期必須為 1、5、15')
    if not isinstance(strategy['blocks'], list) or len(strategy['blocks']) > 200:
        raise ValueError('積木必須為陣列且不超過 200 個')
    blocks = {}
    for b in strategy['blocks']:
        if not isinstance(b, dict) or not all(k in b for k in ('id', 'type', 'name', 'enabled', 'timeframe', 'params', 'output')):
            raise ValueError('每個積木必須包含 id/type/name/enabled/timeframe/params/output')
        if not isinstance(b['id'], str) or not b['id'] or b['id'] in blocks:
            raise ValueError('積木 ID 必須唯一且非空白')
        if b['type'] not in TYPES or b['timeframe'] not in (1, 5, 15) or type(b['enabled']) is not bool or not isinstance(b['params'], dict):
            raise ValueError(f"積木 {b['id']} 型別、週期或參數錯誤")
        expected = 'PriceLevel' if b['type'] in PRICE else 'Event' if b['type'] == 'event' else 'Condition'
        if b['output'] != expected:
            raise ValueError(f"積木 {b['id']} 輸出必須為 {expected}")
        p = b['params']
        for key in ('period', 'left', 'right', 'minutes', 'within'):
            if key in p and (type(p[key]) is not int or not 1 <= p[key] <= 10000):
                raise ValueError(f'{key} 必須為 1–10000 整數')
        if 'direction' in p and p['direction'] not in ('up', 'down'):
            raise ValueError('direction 必須為 up/down')
        if 'field' in p and p['field'] not in ('high', 'low', 'value'):
            raise ValueError('field 必須為 high/low/value')
        if 'tolerance' in p and (not isinstance(p['tolerance'], (float, int)) or not math.isfinite(p['tolerance']) or p['tolerance'] < 0):
            raise ValueError('回踩容許點數須為非負有限值')
        if b['type'] in ('and', 'or', 'sequence'):
            ins = p.get('inputs')
            if not isinstance(ins, list) or len(ins) < 2 or (b['type'] == 'sequence' and len(ins) != 2):
                raise ValueError('AND/OR 至少兩個輸入；順序等待恰好兩個')
        blocks[b['id']] = b
    ordered, visiting, done = [], set(), set()

    def visit(id):
        if not isinstance(id, str) or id not in blocks:
            raise ValueError(f'引用不存在的積木：{id}')
        if id in visiting:
            raise ValueError('積木不可循環依賴')
        if id in done:
            return
        visiting.add(id)
        b = blocks[id]
        for dep_index, dep in enumerate(dependencies(b)):
            visit(dep)
            source = blocks[dep]
            expected = 'PriceLevel' if b['type'] in ('breakout', 'retest', 'compare') or (b['type'] == 'snapshot' and dep_index == 0) else 'Condition'
            if source['output'] != expected:
                raise ValueError(f'{id} 的輸入 {dep} 必須是 {expected}')
            if b['enabled'] and not source['enabled']:
                raise ValueError(f'{id} 引用未啟用的積木 {dep}')
        visiting.remove(id)
        done.add(id)
        ordered.append(b)
    for id in blocks:
        visit(id)
    for section in ('entries', 'exits'):
        for side in ('long', 'short'):
            id = strategy[section].get(side)
            if id is not None and (id not in blocks or blocks[id]['output'] == 'PriceLevel' or not blocks[id]['enabled']):
                raise ValueError(f'{section}.{side} 必須引用啟用的 Condition 或 Event')
    risk = strategy['risk']
    for key in ('stop_points', 'target_points'):
        value = risk.get(key)
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
            raise ValueError(f'{key} 必須為正數或 null')
    structure = risk.get('structure_source')
    if structure is not None and (structure not in blocks or blocks[structure]['output'] != 'PriceLevel' or not blocks[structure]['enabled']):
        raise ValueError('結構停損必須引用啟用的 PriceLevel')
    for key in ('point_value', 'commission', 'tax_rate', 'tax_fixed', 'slippage', 'initial_capital'):
        v = strategy['costs'].get(key)
        if not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or (key in ('point_value', 'initial_capital') and v == 0):
            raise ValueError(f'成本 {key} 必須為有限非負值；每點價值與初始資金須大於零')
    if strategy['costs'].get('tax_mode') not in ('notional', 'fixed'):
        raise ValueError('交易稅模式須為 notional 或 fixed')
    if strategy['execution'] != {'entry': 'next_open', 'collision': 'stop_first'}:
        raise ValueError('V1 成交設定須為 next_open / stop_first')
    limit = strategy['limits']
    for key in ('entry_start', 'entry_end'):
        from datetime import time
        try:
            time.fromisoformat(limit[key])
        except (KeyError, ValueError, TypeError):
            raise ValueError('進場時段格式須為 HH:MM') from None
    if not '08:45' <= limit['entry_start'] < limit['entry_end'] <= '13:45':
        raise ValueError('進場時段必須在 08:45–13:45 內')
    if type(limit.get('max_trades_per_day')) is not int or limit['max_trades_per_day'] < 1:
        raise ValueError('每日最大交易數必須為正整數')
    return ordered


class Evaluator:
    def __init__(self, strategy, series):
        self.blocks = validate(strategy)
        self.series = series
        self.ends = {tf: [b.end for b in bars] for tf, bars in series.items()}
        self.values, self.states, self.processed = {}, {}, {}

    def step(self, now):
        for b in self.blocks:
            id, kind, p, tf = b['id'], b['type'], b['params'], b['timeframe']
            if not b['enabled']:
                continue
            count = bisect_right(self.ends[tf], now)
            if count == 0 or self.processed.get(id) == count:
                continue
            self.processed[id] = count
            bars = self.series[tf]
            current = bars[count - 1]
            stamp = current.end
            state = self.states.setdefault(id, {})
            value = None
            detail = ''
            if kind == 'opening_range':
                anchor = current.start.replace(hour=8, minute=45)
                end = anchor + timedelta(minutes=p.get('minutes', 5))
                if stamp >= end:
                    left = bisect_right(self.ends[tf], anchor)
                    right = bisect_right(self.ends[tf], end)
                    rows = bars[left:right]
                    if len(rows) * tf == p.get('minutes', 5) and rows[0].start == anchor and rows[-1].end == end:
                        value = {'high': max(x.high for x in rows), 'low': min(x.low for x in rows)}
            elif kind == 'snapshot':
                trigger = self.values.get(p['trigger'])
                source = self.values.get(p['source'])
                if state.get('day') != stamp.date():
                    state.clear()
                    state['day'] = stamp.date()
                if trigger and trigger['value'] and trigger['at'] == stamp and source and source['value']:
                    state['level'] = source['value'].copy()
                value = state.get('level')
            elif kind in ('ma', 'rolling_range'):
                n = p.get('period', 20)
                end = count if kind == 'ma' else count - 1
                rows = bars[max(0, end - n):end]
                if len(rows) == n:
                    value = {'value': sum(x.close for x in rows) / n} if kind == 'ma' else {'high': max(x.high for x in rows), 'low': min(x.low for x in rows)}
            elif kind == 'swing':
                left, right = p.get('left', 2), p.get('right', 2)
                i = count - 1 - right
                value = state.get('levels', {}).copy()
                if i >= left:
                    pivot = bars[i]
                    neighbors = bars[i-left:i] + bars[i+1:i+right+1]
                    if all(pivot.high > x.high for x in neighbors):
                        value['high'] = pivot.high
                    if all(pivot.low < x.low for x in neighbors):
                        value['low'] = pivot.low
                    state['levels'] = value
                value = value or None
            else:
                truth = False
                if kind in ('breakout', 'compare', 'retest'):
                    src = self.values.get(p['source'])
                    level = src['value'].get(p.get('field', 'high')) if src and src['value'] else None
                    if level is not None:
                        up = p.get('direction', 'up') == 'up'
                        detail = f"收盤 {current.close}，參考 {p['source']}.{p.get('field', 'high')}={level}，方向 {p.get('direction', 'up')}"
                        if kind == 'breakout':
                            prev = bars[count - 2] if count >= 2 else None
                            truth = bool(prev and (prev.close <= level < current.close if up else prev.close >= level > current.close))
                        elif kind == 'compare':
                            truth = current.close > level if up else current.close < level
                        else:
                            tol = p.get('tolerance', 2)
                            detail += f'，高低區間 {current.low}–{current.high}，容許 {tol} 點'
                            truth = (current.low <= level + tol and current.high >= level - tol and
                                     (current.close > level if up else current.close < level))
                elif kind == 'candle':
                    truth = current.close > current.open if p.get('direction', 'up') == 'up' else current.close < current.open
                    detail = f'開盤 {current.open}，收盤 {current.close}'
                elif kind in ('and', 'or', 'sequence'):
                    inputs = [self.values.get(dep) for dep in p['inputs']]
                    # Conditions refer to this trading date; never carry yesterday's signal.
                    flags = [bool(v and v['value'] and v['at'].date() == stamp.date()) for v in inputs]
                    detail = ', '.join(f'{dep}={flag}' for dep, flag in zip(p['inputs'], flags))
                    if kind == 'and':
                        truth = all(flags)
                    elif kind == 'or':
                        truth = any(flags)
                    else:
                        a, other = inputs
                        armed = state.get('armed')
                        if armed and (armed.date() != stamp.date() or stamp - armed > timedelta(minutes=p.get('within', 30))):
                            armed = None
                        if flags[0] and state.get('used_a') != a['at']:
                            armed = a['at']
                            state['used_a'] = a['at']
                        if armed and flags[1] and other['at'] > armed:
                            truth = True
                            detail = f"A={p['inputs'][0]} 於 {armed.isoformat()}；B={p['inputs'][1]} 於 {other['at'].isoformat()}"
                            armed = None
                        state['armed'] = armed
                elif kind == 'event':
                    src = self.values.get(p['source'])
                    active = bool(src and src['value'] and src['at'].date() == stamp.date())
                    truth = active and not state.get('active', False)
                    state['active'] = active
                    detail = f"來源 {p['source']} 由不成立轉為成立"
                value = truth
            self.values[id] = {'value': value, 'at': stamp, 'block_id': id,
                               'reason': f"{b['name']} ({id})：{value}" + (f'；{detail}' if detail else '')}
        return self.values


def templates():
    def block(id, kind, name, params, tf=1):
        return {'id': id, 'type': kind, 'name': name, 'enabled': True, 'timeframe': tf, 'params': params,
                'output': 'PriceLevel' if kind in PRICE else 'Condition'}
    def base(id, name, blocks, risk, exits=None):
        return {'strategy_id': id, 'version': '1.0', 'name': name, 'instrument': 'TX', 'timeframe': 1,
                'blocks': blocks, 'entries': {'long': 'long', 'short': 'short'},
                'exits': exits or {'long': None, 'short': None}, 'risk': risk,
                'limits': {'entry_start': '08:50', 'entry_end': '13:40', 'max_trades_per_day': 10},
                'execution': {'entry': 'next_open', 'collision': 'stop_first'},
                'costs': {'point_value': 200, 'commission': 50, 'tax_mode': 'notional', 'tax_rate': 0.00002,
                          'tax_fixed': 0, 'slippage': 1, 'initial_capital': 1000000}}
    def breaks(source):
        return [block('long', 'breakout', '收盤向上突破', {'source': source, 'field': 'high', 'direction': 'up'}),
                block('short', 'breakout', '收盤向下突破', {'source': source, 'field': 'low', 'direction': 'down'})]
    opening = block('range', 'opening_range', '開盤五分鐘區間', {'minutes': 5})
    fixed = base('opening-fixed', '開盤 5 分 K 區間突破＋固定停損', [opening] + breaks('range'), {'stop_points': 30, 'target_points': 60})
    ma = base('opening-ma', '開盤 5 分 K 區間突破＋MA20 出場', [opening] + breaks('range') + [
        block('ma20', 'ma', 'MA20', {'period': 20}),
        block('exit-long', 'compare', '收盤低於 MA20', {'source': 'ma20', 'field': 'value', 'direction': 'down'}),
        block('exit-short', 'compare', '收盤高於 MA20', {'source': 'ma20', 'field': 'value', 'direction': 'up'})],
        {'stop_points': 30, 'target_points': None}, {'long': 'exit-long', 'short': 'exit-short'})
    swing = base('swing-structure', '前波高低點突破＋結構停損', [block('swing', 'swing', '已確認波段', {'left': 2, 'right': 2})] + breaks('swing'),
                 {'structure_source': 'swing', 'stop_points': None, 'target_points': None})
    rows = [block('sr', 'rolling_range', '前 20 根支撐壓力', {'period': 20})]
    for side, direction, field in [('long', 'up', 'high'), ('short', 'down', 'low')]:
        rows += [block(side + '-break', 'breakout', '突破確認', {'source': 'sr', 'field': field, 'direction': direction}),
                 block(side + '-level', 'snapshot', '鎖定突破時支撐壓力', {'source': 'sr', 'trigger': side + '-break'}),
                 block(side + '-retest', 'retest', '回踩價格區間', {'source': side + '-level', 'field': field, 'direction': direction, 'tolerance': 2}),
                 block(side + '-candle', 'candle', 'K 棒方向確認', {'direction': direction}),
                 block(side + '-confirm', 'and', '回踩且 K 棒確認', {'inputs': [side + '-retest', side + '-candle']}),
                 block(side, 'sequence', '先突破後回踩', {'inputs': [side + '-break', side + '-confirm'], 'within': 30})]
    retest = base('sr-retest', '支撐壓力回踩＋K 棒確認進場', rows, {'stop_points': 30, 'target_points': 60})
    return [fixed, ma, swing, retest]
