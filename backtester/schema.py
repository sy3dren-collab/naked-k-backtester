"""Validation for the expanded strategy schema, including typed risk blocks."""
from datetime import date, time
import math

from .catalog import CATALOG
from .data import TIMEFRAMES


def references(block):
    schema = CATALOG[block['type']]['params']
    for key, spec in schema.items():
        if spec['type'] in ('price_ref', 'condition_ref'):
            yield key, block['params'].get(key, spec['default']), spec['type']
        elif spec['type'] == 'condition_refs':
            for id in block['params'].get(key, []):
                yield key, id, 'condition_ref'


def risk_for(strategy, side):
    risk = strategy['risk']
    return {**{k: v for k, v in risk.items() if k not in ('long', 'short')}, **risk.get(side, {})}


def validate(strategy):
    if not isinstance(strategy, dict):
        raise ValueError('策略必須是 JSON 物件')
    for key in ('strategy_id', 'version', 'instrument', 'timeframe', 'blocks', 'entries', 'exits', 'risk', 'limits', 'execution', 'costs'):
        if key not in strategy:
            raise ValueError('策略缺少 ' + key)
    if not isinstance(strategy['strategy_id'], str) or not strategy['strategy_id'] or not str(strategy['version']):
        raise ValueError('策略 ID 與版本不可空白')
    if strategy['timeframe'] not in TIMEFRAMES:
        raise ValueError('週期須為 1／5／15／30／60 分 K')
    if strategy.get('direction', 'both') not in ('both', 'long', 'short'):
        raise ValueError('交易方向須為 long／short／both')
    if type(strategy.get('quantity', 1)) is not int or not 1 <= strategy.get('quantity', 1) <= 100:
        raise ValueError('單筆口數須為 1–100 整數，仍僅允許單一持倉')
    if not isinstance(strategy['blocks'], list) or len(strategy['blocks']) > 200:
        raise ValueError('策略積木不得超過 200 個')
    blocks = {}
    for block in strategy['blocks']:
        if not isinstance(block, dict) or not all(k in block for k in ('id', 'type', 'name', 'enabled', 'timeframe', 'params', 'output')):
            raise ValueError('積木欄位不完整')
        id, kind = block['id'], block['type']
        if not isinstance(id, str) or not id or id in blocks:
            raise ValueError('積木 ID 須唯一且非空白')
        if kind not in CATALOG or block['output'] != CATALOG[kind]['output']:
            raise ValueError(f'{id}：不支援的積木或輸出型態')
        if block['timeframe'] not in TIMEFRAMES or type(block['enabled']) is not bool or not isinstance(block['params'], dict):
            raise ValueError(f'{id}：週期、啟用狀態或參數錯誤')
        definition = CATALOG[kind]['params']
        for key, value in block['params'].items():
            if key not in definition and key not in ('valid_bars',):
                raise ValueError(f'{id}：未知參數 {key}')
            spec = definition.get(key, {'type': 'integer', 'min': 1, 'max': 10000})
            dtype = spec['type']
            if dtype in ('number', 'integer'):
                if type(value) not in (int, float) or not math.isfinite(value) or (dtype == 'integer' and type(value) is not int):
                    raise ValueError(f'{id}.{key}：須為有效數值')
                if value < spec.get('min', -math.inf) or value > spec.get('max', math.inf):
                    raise ValueError(f'{id}.{key}：數值超出範圍')
            elif dtype == 'boolean' and type(value) is not bool:
                raise ValueError(f'{id}.{key}：須為開關')
            elif dtype == 'select' and value not in spec['choices']:
                raise ValueError(f'{id}.{key}：選項不合法')
            elif dtype == 'time':
                try:
                    time.fromisoformat(value)
                except (ValueError, TypeError):
                    raise ValueError(f'{id}.{key}：時間格式須為 HH:MM') from None
            elif dtype in ('condition_refs', 'integer_list', 'date_list') and not isinstance(value, list):
                raise ValueError(f'{id}.{key}：須為清單')
            if dtype == 'integer_list' and any(type(x) is not int or x not in range(7) for x in value):
                raise ValueError('星期須為週一=0 至週日=6')
            if dtype == 'date_list':
                for item in value:
                    date.fromisoformat(item)
        p = block['params']
        if kind in ('and', 'or', 'sequence') and len(p.get('inputs', [])) < 2:
            raise ValueError(f'{id}：至少需要兩個輸入')
        if kind in ('stop_fixed', 'target_fixed') and p.get('points', 30) <= 0:
            raise ValueError('停損／停利點數須大於零')
        if kind == 'stop_trailing_points' and p.get('distance', 10) <= 0:
            raise ValueError('追蹤距離須大於零')
        if kind == 'target_rr' and p.get('ratio', 2) <= 0:
            raise ValueError('R 倍數須大於零')
        for low, high in (('minimum', 'maximum'), ('min_width', 'max_width'), ('min_retrace', 'max_retrace')):
            if low in p and high in p and p[low] > p[high]:
                raise ValueError(f'{id}：最小值不可大於最大值')
        blocks[id] = block
    ordered, visiting, done = [], set(), set()
    def visit(id):
        if not isinstance(id, str) or id not in blocks:
            raise ValueError(f'引用不存在的積木：{id}')
        if id in visiting:
            raise ValueError('積木不可循環依賴')
        if id in done:
            return
        visiting.add(id)
        block = blocks[id]
        for key, dep, dtype in references(block):
            visit(dep)
            target = blocks[dep]
            if dtype == 'price_ref' and CATALOG[target['type']]['category'] != 'price':
                raise ValueError(f'{id}.{key}：須引用市場價格積木')
            accepted = CATALOG[block['type']]['params'][key].get('accepts')
            if accepted and target['type'] not in accepted:
                raise ValueError(f'{id}.{key}：價格來源須為 '+ '／'.join(CATALOG[k]['name'] for k in accepted))
            if dtype == 'condition_ref' and target['output'] not in ('Condition', 'Event'):
                raise ValueError(f'{id}.{key}：須引用條件或事件')
            if block['enabled'] and not target['enabled']:
                raise ValueError(f'{id} 引用未啟用的積木 {dep}')
        visiting.remove(id); done.add(id); ordered.append(block)
    for id in blocks:
        visit(id)
    for section in ('entries', 'exits'):
        for side in ('long', 'short'):
            root = strategy[section].get(side)
            for id in root if isinstance(root, list) else [root]:
                if id is not None and (id not in blocks or blocks[id]['output'] not in ('Condition', 'Event') or not blocks[id]['enabled']):
                    raise ValueError(f'{section}.{side}：必須引用啟用的條件或事件')
    for side in ('long', 'short'):
        risk = risk_for(strategy, side)
        for key, category in (('stop_blocks', 'stop'), ('target_blocks', 'target')):
            for id in risk.get(key, []):
                if id not in blocks or CATALOG[blocks[id]['type']]['category'] != category or not blocks[id]['enabled']:
                    raise ValueError(f'{side}.{key}：引用的積木類型不合法')
        for key in ('stop_points', 'target_points'):
            value = risk.get(key)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
                raise ValueError(key + ' 須為正數或空白')
        source = risk.get('structure_source')
        if source and (source not in blocks or CATALOG[blocks[source]['type']]['category'] != 'price'):
            raise ValueError('結構停損須引用市場價格')
    for key in ('point_value', 'commission', 'tax_rate', 'tax_fixed', 'slippage', 'initial_capital'):
        value = strategy['costs'].get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (key in ('point_value', 'initial_capital') and value == 0):
            raise ValueError('成本參數錯誤：' + key)
    if strategy['costs'].get('tax_mode') not in ('notional', 'fixed'):
        raise ValueError('交易稅模式不合法')
    execution = strategy['execution']
    if execution.get('entry') not in ('next_open', 'touch') or execution.get('collision') != 'stop_first':
        raise ValueError('成交方式須為 next_open／touch，且停損優先')
    if type(execution.get('valid_bars', 3)) is not int or execution.get('valid_bars', 3) < 1:
        raise ValueError('委託有效根數須為正整數')
    if execution.get('entry') == 'touch':
        source = execution.get('source')
        if source not in blocks or CATALOG[blocks[source]['type']]['category'] != 'price':
            raise ValueError('觸價委託須設定已確認的價格來源')
        if execution.get('field', 'high') not in ('high', 'low', 'mid', 'value'):
            raise ValueError('觸價委託價位須為 high／low／mid／value')
    limits = strategy['limits']
    for key in ('entry_start', 'entry_end', 'force_close'):
        try:
            time.fromisoformat(limits.get(key, '13:45'))
        except (ValueError, TypeError):
            raise ValueError('時間限制格式須為 HH:MM') from None
    if not '08:45' <= limits['entry_start'] < limits['entry_end'] <= '13:45' or not limits['entry_end'] <= limits.get('force_close', '13:45') <= '13:45':
        raise ValueError('日盤與進出場時間限制不合法')
    if type(limits.get('max_trades_per_day')) is not int or limits['max_trades_per_day'] < 1:
        raise ValueError('每日最多交易數須為正整數')
    for key in ('daily_max_loss', 'cooldown_bars', 'max_stop_distance', 'min_space'):
        value = limits.get(key, 0)
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise ValueError(key + ' 不可為負數')
    weekdays = limits.get('excluded_weekdays', [])
    if not isinstance(weekdays, list) or any(type(v) is not int or v not in range(7) for v in weekdays):
        raise ValueError('排除星期須為週一=0 至週日=6 的清單')
    for item in limits.get('excluded_dates', []): date.fromisoformat(item)
    return ordered
