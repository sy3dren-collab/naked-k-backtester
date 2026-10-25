"""Extended event loop using the independent matching module."""
import copy
import hashlib
from datetime import date, timedelta

from .blocks import Evaluator
from .catalog import CATALOG
from .data import aggregate, TIMEFRAMES
from .engine import canonical, metrics
from .matching import Broker
from .schema import validate, references

ENGINE_VERSION = '2.1.0'


def roots(value):
    return value if isinstance(value, list) else [value] if value else []


def run(bars, strategy, settings=None):
    validate(strategy)
    settings = settings or {}
    start = date.fromisoformat(settings['start']) if settings.get('start') else date.min
    end = date.fromisoformat(settings['end']) if settings.get('end') else date.max
    if start > end: raise ValueError('開始日期不可晚於結束日期')
    series = {tf: aggregate(bars, tf) for tf in TIMEFRAMES}
    minutes = series[1]
    evaluator, broker = Evaluator(strategy, series), Broker(strategy)
    limits, execution = strategy['limits'], strategy['execution']
    last_of_day = {b.start.date(): b for b in minutes}
    equity, signals, overlays, used = [], [], [], set()
    logged = set()
    pending = None
    blocks = {b['id']: b for b in strategy['blocks']}
    def event_id(id, at):
        return hashlib.sha256(canonical([strategy['strategy_id'], strategy['version'], id, at.isoformat()]).encode()).hexdigest()[:24]
    def permitted(day, at):
        daily_loss = limits.get('daily_max_loss', 0)
        return (limits['entry_start'] <= at.strftime('%H:%M') < limits['entry_end']
                and day.weekday() not in limits.get('excluded_weekdays', []) and day.isoformat() not in limits.get('excluded_dates', [])
                and broker.daily_count.get(day, 0) < limits['max_trades_per_day']
                and (not daily_loss or broker.daily_pnl.get(day, 0) > -daily_loss)
                and (not broker.last_stop or (at-broker.last_stop).total_seconds()/60 >= limits.get('cooldown_bars', 0)*strategy['timeframe']))
    for index, b in enumerate(minutes):
        today, in_range, exited = b.start.date(), start <= b.start.date() <= end, False
        if in_range and broker.position:
            exited = broker.gap_stop(b)
        if in_range and pending:
            if pending['day'] != today or b.start > pending.get('expires', b.start): pending = None
            elif pending['kind'] == 'exit':
                if broker.position:
                    broker.close(b.open, b.start, pending['reason'], pending['block_id']); exited = True
                pending = None
            elif not exited and not broker.position:
                if not permitted(today, b.start): pending = None
                elif execution['entry'] == 'next_open':
                    broker.enter(pending, b); pending = None
                else:
                    trigger, d = pending.get('trigger'), pending['direction']
                    if trigger is not None and (b.high >= trigger if d == 1 else b.low <= trigger):
                        raw = max(b.open, trigger) if d == 1 else min(b.open, trigger)
                        broker.enter(pending, b, raw, intrabar=raw != b.open); pending = None
        if in_range and broker.position:
            exited = broker.protect(b) or exited
        if in_range and broker.position:
            # Extremes are known at this close; the new protection is active from the next bar.
            broker.update_after_close(b, evaluator.values)
        context = {'position': broker.position, 'daily_trades': broker.daily_count.get(today, 0),
                   'daily_pnl': broker.daily_pnl.get(today, 0),
                   'since_stop': (b.end-broker.last_stop).total_seconds()/60 if broker.last_stop else float('inf')}
        values = evaluator.step(b.end, context)
        if not in_range: continue
        if broker.position:
            # Confirmed structural levels from this close can update next bar's stop.
            broker.update_after_close(b, values)
        for id, value in values.items():
            if value['at'] != b.end: continue
            if value['value'] is True:
                eid = event_id(id, value.get('origin_at', b.end))
                if eid not in logged:
                    logged.add(eid)
                    signals.append({'event_id': eid, 'trigger_time': b.end.isoformat(), 'origin_time': value.get('origin_at', b.end).isoformat(), 'strategy_id': strategy['strategy_id'],
                                    'strategy_version': strategy['version'], 'block_id': id, 'reason': value['reason']})
            elif CATALOG[blocks[id]['type']]['category'] == 'price' and value['value'] is not None:
                previous = evaluator.states[id].get('_overlay')
                # Levels and newly confirmed pivots are saved at their confirmation time.
                content = {'value': value['value'], 'meta': value['meta']}
                serialized = canonical(content)
                if previous != serialized:
                    overlays.append({'time': b.end.isoformat(), 'block_id': id, 'name': blocks[id]['name'], 'type': blocks[id]['type'], **copy.deepcopy(content)})
                    evaluator.states[id]['_overlay'] = serialized
        contract_change = index+1 < len(minutes) and b.contract and minutes[index+1].contract and b.contract != minutes[index+1].contract
        forced = last_of_day[today] is b or b.end.strftime('%H:%M') >= limits.get('force_close', '13:45') or contract_change
        if forced:
            pending = None
            if broker.position:
                broker.close(b.close, b.end, '合約換月平倉' if contract_change else '日盤／指定時間強制平倉', 'forced-close', precision='bar_close'); exited = True
        elif broker.position:
            for id in roots(strategy['exits'].get(broker.position['side'])):
                value = values.get(id)
                if value and value['at'] == b.end and value['value'] is True:
                    pending = {'kind': 'exit', 'day': today, 'reason': value['reason'], 'block_id': id}; break
        elif not exited and pending is None and permitted(today, b.end):
            candidates = []
            for side, d in [('long', 1), ('short', -1)]:
                if strategy.get('direction', 'both') not in ('both', side): continue
                for id in roots(strategy['entries'].get(side)):
                    value = values.get(id); key = (id, value.get('origin_at', b.end)) if value else (id, b.end)
                    if not value or value['at'] != b.end or value['value'] is not True or key in used: continue
                    used.add(key)
                    signal_tf = blocks[id]['timeframe']; signal_series = series[signal_tf]
                    from bisect import bisect_right
                    count = bisect_right(evaluator.ends[signal_tf], b.end)
                    candidate = {'kind': 'entry', 'day': today, 'at': b.end, 'side': side, 'direction': d, 'block_id': id,
                                 'signal_id': event_id(id, value.get('origin_at', b.end)), 'reason': value['reason'],
                                 'signal_bar': signal_series[count-1], 'previous_bar': signal_series[count-2] if count > 1 else None,
                                 'values': copy.deepcopy(values), 'expires': b.end+timedelta(minutes=execution.get('valid_bars', 3)*strategy['timeframe'])}
                    visited, constraints = set(), []
                    def entry_constraints(node):
                        if node in visited: return
                        visited.add(node); child = blocks[node]; params = child['params']
                        if child['type'] == 'breakout' and params.get('max_chase'):
                            edge = evaluator.states[node].get('reference')
                            if edge is not None: constraints.append({'level': edge, 'maximum': params['max_chase'], 'block_id': node})
                        for _,dep,_ in references(child): entry_constraints(dep)
                    entry_constraints(id); candidate['chase_constraints'] = constraints
                    if execution['entry'] == 'touch':
                        candidate['trigger'] = broker.level(values, execution['source'], execution.get('field', 'high' if d == 1 else 'low'))
                    source = blocks[id]['params'].get('source')
                    candidate['break_level'] = broker.level(values, source, 'high' if d == 1 else 'low')
                    candidates.append(candidate); break
            if len(candidates) == 1: pending = candidates[0]
            elif len(candidates) > 1: broker.warnings.append(f'{b.end.isoformat()}：多空同時成立，保守略過')
        equity.append({'time': b.end.isoformat(), 'equity': broker.equity(b.close)})
    if not equity: raise ValueError('所選日期沒有可回測的日盤資料')
    result = {'engine_version': ENGINE_VERSION, 'strategy': strategy, 'settings': settings, 'trades': broker.trades,
              'signals': signals, 'equity': equity, 'overlays': overlays, 'protection_updates': broker.updates, 'warnings': broker.warnings,
              'assumptions': ['單商品、單一持倉、不加碼；同棒出場後不立即反手',
                              '所有價格與結構只在其確認時間後可用；移動停損從下一分鐘生效',
                              '觸價委託只在訊號確認後的 1 分 K 檢查，盤中路徑不明採停損優先並標記',
                              '每日虧損限制以已實現淨損益阻止新進場；不假設可精確限制盤中浮虧',
                              '回撤採分鐘收盤淨清算值；成本為使用者設定，非最新實際費率',
                              '未內建交易所假日；缺少尾盤資料時在最後可用日盤 K 平倉']}
    result['metrics'] = metrics(broker.trades, equity, strategy['costs']['initial_capital'], extended=True)
    return result
