"""Single-position matching, costs and protection orders, independent of signals."""
from datetime import timedelta

from .catalog import CATALOG
from .schema import risk_for


class Broker:
    def __init__(self, strategy):
        self.strategy = strategy
        self.costs = strategy['costs']
        self.quantity = strategy.get('quantity', 1)
        self.blocks = {b['id']: b for b in strategy['blocks']}
        self.position = None
        self.realized = 0.0
        self.trades, self.updates, self.warnings = [], [], []
        self.daily_pnl, self.daily_count = {}, {}
        self.last_stop = None

    def fee(self, price):
        c = self.costs
        tax = price*c['point_value']*c['tax_rate'] if c['tax_mode'] == 'notional' else c['tax_fixed']
        return {'commission': c['commission']*self.quantity, 'tax': tax*self.quantity}

    def fill(self, raw, direction, entering):
        value = raw+self.costs['slippage']*direction*(1 if entering else -1)
        if value <= 0:
            raise ValueError('滑價後成交價不為正值，請檢查滑價及商品設定')
        return value

    def rules(self, risk, key):
        return [self.blocks[id] for id in risk.get(key, []) if self.blocks[id]['enabled']]

    @staticmethod
    def level(values, source, field):
        value = values.get(source)
        return value['value'].get(field) if value and isinstance(value['value'], dict) else None

    def enter(self, plan, bar, raw=None, intrabar=False):
        if self.position:
            raise RuntimeError('單一持倉限制：不得重複進場')
        d, side, values = plan['direction'], plan['side'], plan['values']
        risk = risk_for(self.strategy, side)
        raw = bar.open if raw is None else raw
        price = self.fill(raw, d, True)
        stops, targets = [], []
        signal_bar, previous = plan['signal_bar'], plan['previous_bar']
        def add_stop(value, id):
            if value is None or (price-value)*d <= 0:
                raise ValueError(f'{id}：進場後保護價無效或尚未確認')
            stops.append((value, id))
        try:
            for constraint in plan.get('chase_constraints', []):
                if abs(price-constraint['level']) > constraint['maximum']:
                    raise ValueError(f'{constraint["block_id"]}：成交時追價距離超過上限')
            if risk.get('stop_points'):
                add_stop(price-d*risk['stop_points'], 'fixed-stop')
            if risk.get('structure_source'):
                add_stop(self.level(values, risk['structure_source'], 'low' if d == 1 else 'high'), risk['structure_source'])
            for block in self.rules(risk, 'stop_blocks'):
                kind, p, id = block['type'], block['params'], block['id']
                if kind == 'stop_trailing_points':
                    continue
                if kind == 'stop_fixed': value = price-d*p.get('points', 30)
                elif kind in ('stop_signal', 'stop_previous'):
                    source_bar = signal_bar if kind == 'stop_signal' else previous
                    value = (source_bar.low if d == 1 else source_bar.high)-d*p.get('buffer', 0) if source_bar else None
                else:
                    edge = self.level(values, p['source'], 'low' if d == 1 else 'high')
                    if kind == 'stop_structure' and p.get('mode') == 'hl_lh':
                        pivots = values.get(p['source'], {}).get('meta', {}).get('pivots', [])
                        points = [x['price'] for x in pivots if x['kind'] == ('low' if d == 1 else 'high')]
                        if len(points) < 2 or (points[-1]-points[-2])*d <= 0:
                            edge = None
                    value = edge-d*p.get('buffer', 0) if edge is not None else None
                add_stop(value, id)
                if p.get('maximum') and abs(price-value) > p['maximum']:
                    raise ValueError(f'{id}：結構停損超過最大距離')
            stop, stop_id = (max(stops) if d == 1 else min(stops)) if stops else (None, None)
            distance = abs(price-stop) if stop is not None else None
            maximum = self.strategy['limits'].get('max_stop_distance', 0)
            if maximum and (distance is None or distance > maximum):
                raise ValueError('停損距離超過允許值或缺少保護價')
            if risk.get('target_points'):
                targets.append((price+d*risk['target_points'], 'fixed-target'))
            for block in self.rules(risk, 'target_blocks'):
                kind, p = block['type'], block['params']
                if kind == 'target_fixed': target = price+d*p.get('points', 60)
                elif kind == 'target_rr':
                    if distance is None: raise ValueError('R 倍數停利需要有效的初始停損')
                    target = price+d*distance*p.get('ratio', 2)
                else:
                    target = self.level(values, p['source'], 'high' if d == 1 else 'low')
                    zones = values.get(p['source'], {}).get('meta', {}).get('zones', [])
                    usable = [z for z in zones if z['role'] == ('resistance' if d == 1 else 'support') and (z['center']-price)*d > 0]
                    if usable:
                        selected = min(usable, key=lambda z: abs(z['center']-price))
                        target = selected['low' if d == 1 else 'high']
                    if target is not None: target -= d*p.get('buffer', 0)
                if target is None or (target-price)*d <= 0:
                    raise ValueError(f'{block["id"]}：停利參考價不在有利方向')
                targets.append((target, block['id']))
            target, target_id = (min(targets) if d == 1 else max(targets)) if targets else (None, None)
            minimum_space = self.strategy['limits'].get('min_space', 0)
            if minimum_space and (target is None or abs(target-price) < minimum_space):
                raise ValueError('至停利／支撐壓力的剩餘空間不足')
        except ValueError as error:
            self.warnings.append(f'{bar.start.isoformat()}：取消進場；{error}')
            return False
        self.position = {'position_id': len(self.trades)+1, 'side': side, 'direction': d, 'quantity': self.quantity,
                         'entry_time': bar.start, 'entry_price': price, 'raw_entry_price': raw, 'entry_fee': self.fee(price),
                         'stop': stop, 'target': target, 'initial_stop': stop, 'initial_risk_points': distance,
                         'stop_block_id': stop_id, 'target_block_id': target_id, 'entry_block_id': plan['block_id'],
                         'entry_reason': plan['reason'], 'signal_id': plan['signal_id'], 'signal_time': plan['at'].isoformat(),
                         'strategy_id': self.strategy['strategy_id'], 'strategy_version': self.strategy['version'],
                         'entry_intrabar_uncertain': intrabar, 'best_price': price, 'best_points': 0, 'structure_peak': price,
                         'reference_at_entry': {id: dict(v['value']) for id,v in values.items() if isinstance(v['value'], dict)},
                         'break_level': plan.get('break_level')}
        self.daily_count[bar.start.date()] = self.daily_count.get(bar.start.date(), 0)+1
        self.record_update(bar.start)
        return True

    def record_update(self, at):
        p = self.position
        self.updates.append({'time': at.isoformat(), 'position_id': p['position_id'], 'stop': p['stop'], 'target': p['target'],
                             'stop_block_id': p['stop_block_id'], 'target_block_id': p['target_block_id']})

    def close(self, raw, at, reason, block_id=None, ambiguous=False, precision='bar_open', stopped=False):
        p = self.position
        price = self.fill(raw, p['direction'], False)
        exit_fee = self.fee(price)
        gross = (price-p['entry_price'])*p['direction']*self.costs['point_value']*self.quantity
        cost = sum(p['entry_fee'].values())+sum(exit_fee.values())
        net = gross-cost
        self.realized += net
        self.daily_pnl[at.date()] = self.daily_pnl.get(at.date(), 0)+net
        risk_cash = p['initial_risk_points']*self.costs['point_value']*self.quantity if p['initial_risk_points'] else None
        self.trades.append({**p, 'entry_time': p['entry_time'].isoformat(), 'exit_time': at.isoformat(), 'exit_price': price,
                            'raw_exit_price': raw, 'exit_fee': exit_fee, 'cost': cost,
                            'slippage_cost': 2*self.costs['slippage']*self.costs['point_value']*self.quantity,
                            'gross_pnl': gross, 'net_pnl': net, 'realized_r': net/risk_cash if risk_cash else None,
                            'exit_reason': reason, 'exit_block_id': block_id, 'ambiguous_order': ambiguous,
                            'exit_time_precision': precision, 'equity_after': self.costs['initial_capital']+self.realized})
        if stopped:
            # The exact intraminute time is unknown; cooldown starts after that bar completes.
            self.last_stop = at+timedelta(minutes=1) if precision != 'bar_close' else at
        self.position = None

    def gap_stop(self, bar):
        p = self.position
        if p and p['stop'] is not None and (bar.open <= p['stop'] if p['direction'] == 1 else bar.open >= p['stop']):
            self.close(bar.open, bar.start, '跳空停損', p['stop_block_id'], precision='bar_open', stopped=True)
            return True
        return False

    def protect(self, bar):
        p = self.position
        if not p: return False
        d, stop, target = p['direction'], p['stop'], p['target']
        stop_hit = stop is not None and (bar.low <= stop if d == 1 else bar.high >= stop)
        target_hit = target is not None and (bar.high >= target if d == 1 else bar.low <= target)
        if stop_hit:
            gap = bar.open <= stop if d == 1 else bar.open >= stop
            self.close(bar.open if gap else stop, bar.start, '跳空停損' if gap else '保護停損', p['stop_block_id'],
                       ambiguous=bool(target_hit), precision='bar_open' if gap else 'within_1m_bar', stopped=True)
            return True
        if target_hit:
            self.close(target, bar.start, '觸價停利', p['target_block_id'], precision='within_1m_bar')
            return True
        return False

    def update_after_close(self, bar, values):
        p = self.position
        if not p: return
        d = p['direction']
        p['best_price'] = max(p['best_price'], bar.high) if d == 1 else min(p['best_price'], bar.low)
        p['best_points'] = max(0, (p['best_price']-p['entry_price'])*d)
        changed = False
        for block in self.rules(risk_for(self.strategy, p['side']), 'stop_blocks'):
            kind, params = block['type'], block['params']
            candidate = None
            if kind == 'stop_trailing_points' and p['best_points'] >= params.get('activate', 20):
                candidate = p['best_price']-d*params.get('distance', 10)
            elif kind == 'stop_trailing_structure':
                source = values.get(params['source'])
                new_extreme = (p['best_price']-p['structure_peak'])*d > 0
                if source and source['at'] == bar.end and (not params.get('new_extreme', True) or new_extreme):
                    level = self.level(values, params['source'], 'low' if d == 1 else 'high')
                    if level is not None:
                        candidate = level-d*params.get('buffer', 0)
                        p['structure_peak'] = p['best_price']
            if candidate is not None and (p['stop'] is None or (candidate-p['stop'])*d > 0):
                p['stop'] = candidate; p['stop_block_id'] = block['id']; changed = True
        if changed:
            self.record_update(bar.end)

    def equity(self, close):
        value = self.costs['initial_capital']+self.realized
        p = self.position
        if p:
            mark = self.fill(close, p['direction'], False)
            value += (mark-p['entry_price'])*p['direction']*self.costs['point_value']*self.quantity-sum(p['entry_fee'].values())-sum(self.fee(mark).values())
        return value
