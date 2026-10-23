import hashlib
import json
from datetime import date

from .data import aggregate
from .strategy import Evaluator, validate


ENGINE_VERSION = '1.0.0'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def run(bars, strategy, settings=None):
    if strategy.get('schema_version') == 2:
        from .runner import run as run_extended
        return run_extended(bars, strategy, settings)
    validate(strategy)
    settings = settings or {}
    start = date.fromisoformat(settings['start']) if settings.get('start') else date.min
    end = date.fromisoformat(settings['end']) if settings.get('end') else date.max
    if start > end:
        raise ValueError('開始日期不可晚於結束日期')
    # Warmup may use earlier completed bars, never later bars. Trading is date-filtered.
    series = {tf: aggregate(bars, tf) for tf in (1, 5, 15)}
    minutes = series[1]
    evaluator = Evaluator(strategy, series)
    costs, risk, limits = strategy['costs'], strategy['risk'], strategy['limits']
    capital, realized = costs['initial_capital'], 0.0
    position, pending = None, None
    trades, signals, equity, warnings = [], [], [], []
    used, daily = set(), {}
    last_of_day = {b.start.date(): b for b in minutes}

    def fee(price):
        tax = price * costs['point_value'] * costs['tax_rate'] if costs['tax_mode'] == 'notional' else costs['tax_fixed']
        return {'commission': costs['commission'], 'tax': tax}

    def fill(raw_price, direction, entering):
        return raw_price + costs['slippage'] * direction * (1 if entering else -1)

    def close(raw_price, at, reason, ambiguous=False, time_precision='bar_open'):
        nonlocal position, realized
        p = position
        price = fill(raw_price, p['direction'], False)
        exit_fee = fee(price)
        gross = (price - p['entry_price']) * p['direction'] * costs['point_value']
        total = sum(p['entry_fee'].values()) + sum(exit_fee.values())
        net = gross - total
        realized += net
        trades.append({**p, 'entry_time': p['entry_time'].isoformat(), 'exit_time': at.isoformat(),
                       'exit_price': price, 'raw_exit_price': raw_price, 'exit_fee': exit_fee,
                       'cost': total, 'slippage_cost': 2 * costs['slippage'] * costs['point_value'],
                       'gross_pnl': gross, 'net_pnl': net, 'exit_reason': reason,
                       'ambiguous_order': ambiguous, 'exit_time_precision': time_precision,
                       'equity_after': capital + realized})
        position = None

    for b in minutes:
        today = b.start.date()
        in_range = start <= today <= end
        exited = False
        if in_range and pending:
            if pending['day'] == today:
                if pending['kind'] == 'exit' and position:
                    close(b.open, b.start, pending['reason'])
                    exited = True
                elif pending['kind'] == 'entry' and not position and limits['entry_start'] <= b.start.strftime('%H:%M') < limits['entry_end']:
                    direction = pending['direction']
                    price = fill(b.open, direction, True)
                    stop = price - direction * risk['stop_points'] if risk.get('stop_points') else None
                    if risk.get('structure_source'):
                        stop = pending['structure_stop']
                    if stop is not None and (price - stop) * direction <= 0:
                        warnings.append(f'{b.start.isoformat()}：跳空後結構停損位無效，取消進場')
                    elif risk.get('structure_source') and stop is None:
                        warnings.append(f'{b.start.isoformat()}：結構停損位尚未確認，取消進場')
                    else:
                        position = {'side': 'long' if direction == 1 else 'short', 'direction': direction,
                                    'quantity': 1, 'entry_time': b.start, 'entry_price': price, 'raw_entry_price': b.open,
                                    'entry_fee': fee(price), 'stop': stop,
                                    'target': price + direction * risk['target_points'] if risk.get('target_points') else None,
                                    'entry_reason': pending['reason'], 'signal_id': pending['signal_id'],
                                    'strategy_id': strategy['strategy_id'], 'strategy_version': strategy['version']}
                        daily[today] = daily.get(today, 0) + 1
            pending = None
        if in_range and position:
            d, stop, target = position['direction'], position['stop'], position['target']
            stop_hit = stop is not None and (b.low <= stop if d == 1 else b.high >= stop)
            target_hit = target is not None and (b.high >= target if d == 1 else b.low <= target)
            if stop_hit:
                gap = b.open <= stop if d == 1 else b.open >= stop
                close(b.open if gap else stop, b.start, '跳空停損' if gap else '固定／結構停損',
                      bool(target_hit), 'bar_open' if gap else 'within_1m_bar')
                exited = True
            elif target_hit:
                close(target, b.start, '觸價停利', False, 'within_1m_bar')
                exited = True
        values = evaluator.step(b.end)
        if not in_range:
            continue
        for id, value in values.items():
            if value['at'] != b.end or value['value'] is not True:
                continue
            event_id = hashlib.sha256(canonical([strategy['strategy_id'], strategy['version'], id, b.end.isoformat()]).encode()).hexdigest()[:24]
            signals.append({'event_id': event_id, 'trigger_time': b.end.isoformat(), 'strategy_version': strategy['version'],
                            'strategy_id': strategy['strategy_id'], 'block_id': id, 'reason': value['reason']})
        is_last = last_of_day[today] is b
        if is_last:
            pending = None
            if position:
                close(b.close, b.end, '日盤結束強制平倉（資料不足時使用當日末棒）', False, 'bar_close')
                exited = True
        elif position:
            id = strategy['exits'].get(position['side'])
            signal = values.get(id)
            if signal and signal['value'] is True and signal['at'] == b.end:
                pending = {'kind': 'exit', 'day': today, 'reason': signal['reason']}
        elif not exited and daily.get(today, 0) < limits['max_trades_per_day']:
            candidates = []
            for side, direction in [('long', 1), ('short', -1)]:
                id = strategy['entries'].get(side)
                signal = values.get(id)
                if not signal or signal['value'] is not True or signal['at'] != b.end:
                    continue
                key = (id, signal['at'])
                if key in used:
                    continue
                used.add(key)
                if not limits['entry_start'] <= b.end.strftime('%H:%M') < limits['entry_end']:
                    continue
                source = values.get(risk.get('structure_source'))
                level = source['value'].get('low' if direction == 1 else 'high') if source and source['value'] else None
                event_id = hashlib.sha256(canonical([strategy['strategy_id'], strategy['version'], id, b.end.isoformat()]).encode()).hexdigest()[:24]
                candidates.append({'kind': 'entry', 'day': today, 'direction': direction, 'reason': signal['reason'],
                                   'structure_stop': level, 'signal_id': event_id})
            if len(candidates) == 1:
                pending = candidates[0]
            elif len(candidates) > 1:
                warnings.append(f'{b.end.isoformat()}：多空同時成立，保守略過')
        liquidation = 0
        if position:
            mark = fill(b.close, position['direction'], False)
            liquidation = ((mark - position['entry_price']) * position['direction'] * costs['point_value']
                           - sum(position['entry_fee'].values()) - sum(fee(mark).values()))
        equity.append({'time': b.end.isoformat(), 'equity': capital + realized + liquidation})
    if not equity:
        raise ValueError('所選日期範圍沒有可回測的日盤 1 分 K')
    result = {'engine_version': ENGINE_VERSION, 'strategy': strategy, 'settings': settings, 'trades': trades,
              'signals': signals, 'equity': equity, 'warnings': warnings,
              'assumptions': ['台灣時間、日盤 08:45–13:45、單口且不跨日',
                              '同棒停損優先；盤中觸價僅知所在分鐘，不推估秒數',
                              '資金曲線以每分鐘收盤淨清算值計算，未含分鐘內最差浮虧',
                              '週末排除；未內建交易所假日與特殊交易日行事曆',
                              '成本預設為使用者可修改的模擬值，並非最新實際費率']}
    result['metrics'] = metrics(trades, equity, capital)
    return result


def metrics(trades, equity, capital, extended=False):
    wins = [t['net_pnl'] for t in trades if t['net_pnl'] > 0]
    losses = [t['net_pnl'] for t in trades if t['net_pnl'] < 0]
    gross_profit, gross_loss = sum(wins), -sum(losses)
    peak, drawdown, drawdown_pct = capital, 0, 0
    for point in equity:
        value = point['equity']
        peak = max(peak, value)
        drawdown = max(drawdown, peak - value)
        drawdown_pct = max(drawdown_pct, (peak - value) / peak if peak > 0 else 0)
    streak, longest = 0, 0
    monthly = {}
    for t in trades:
        streak = streak + 1 if t['net_pnl'] < 0 else 0
        longest = max(longest, streak)
        month = t['exit_time'][:7]
        monthly[month] = monthly.get(month, 0) + t['net_pnl']
    net = sum(t['net_pnl'] for t in trades)
    result = {'trade_count': len(trades), 'long_count': sum(t['side'] == 'long' for t in trades),
            'short_count': sum(t['side'] == 'short' for t in trades), 'win_rate': len(wins) / len(trades) if trades else 0,
            'gross_profit': gross_profit, 'gross_loss': gross_loss, 'net_pnl': net,
            'average_pnl': net / len(trades) if trades else 0,
            'average_win': gross_profit / len(wins) if wins else 0,
            'average_loss': sum(losses) / len(losses) if losses else 0,
            'profit_factor': gross_profit / gross_loss if gross_loss else None,
            'profit_factor_note': '無虧損；獲利因子無有限值' if not gross_loss else '',
            'max_drawdown': drawdown, 'max_drawdown_pct': drawdown_pct, 'longest_loss_streak': longest,
            'monthly_pnl': monthly, 'final_equity': capital + net,
            'total_cost': sum(t['cost'] for t in trades), 'total_slippage_cost': sum(t['slippage_cost'] for t in trades)}
    if extended:
        daily, periods = {}, {}
        win_streak = longest_win = 0
        loss_amount = max_loss_amount = 0
        for trade in trades:
            pnl = trade['net_pnl']
            day = trade['exit_time'][:10]
            daily[day] = daily.get(day, 0)+pnl
            clock = trade['entry_time'][11:16]
            period = '08:45–10:00' if clock < '10:00' else '10:00–11:30' if clock < '11:30' else '11:30–13:45'
            group = periods.setdefault(period, {'trade_count': 0, 'net_pnl': 0, 'wins': 0})
            group['trade_count'] += 1; group['net_pnl'] += pnl; group['wins'] += pnl > 0
            win_streak = win_streak+1 if pnl > 0 else 0; longest_win = max(longest_win, win_streak)
            loss_amount = loss_amount-pnl if pnl < 0 else 0; max_loss_amount = max(max_loss_amount, loss_amount)
        for group in periods.values(): group['win_rate'] = group['wins']/group['trade_count']
        for side in ('long', 'short'):
            selected = [t for t in trades if t['side'] == side]
            result[side+'_win_rate'] = sum(t['net_pnl'] > 0 for t in selected)/len(selected) if selected else 0
        multiples = [t['realized_r'] for t in trades if t.get('realized_r') is not None]
        result.update({'average_risk_reward': sum(multiples)/len(multiples) if multiples else None,
                       'longest_win_streak': longest_win, 'max_consecutive_loss': max_loss_amount,
                       'daily_pnl': daily, 'time_periods': periods,
                       'cumulative_pnl': [{'time': point['time'], 'pnl': point['equity']-capital} for point in equity]})
    return result
