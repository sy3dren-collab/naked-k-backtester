"""UI schemas and defaults for the extended, Python-backed strategy graph."""


def param(label, default=None, kind='number', choices=None, minimum=0, maximum=None):
    value = {'label': label, 'default': default, 'type': kind}
    if choices is not None:
        value['choices'] = choices
    if kind in ('number', 'integer'):
        value['min'] = minimum
        if maximum is not None:
            value['max'] = maximum
    return value


def integer(label, default=1):
    return param(label, default, 'integer', minimum=1, maximum=10000)


def select(label, default, choices):
    return param(label, default, 'select', choices)


SOURCE = param('價格來源', '', 'price_ref')
DIRECTION = select('方向', 'up', ['up', 'down'])
FIELD = select('參考價格', 'high', ['high', 'low', 'mid', 'open', 'close', 'value'])
BASIS = select('價格判斷', 'wick', ['wick', 'body'])
INPUT = param('條件來源', '', 'condition_ref')
INPUTS = param('條件順序／輸入', [], 'condition_refs')
BUFFER = param('緩衝點數', 0)
CATALOG = {}


def define(kind, code, name, category, output='Condition', **params):
    CATALOG[kind] = {'type': kind, 'code': code, 'name': name, 'category': category,
                     'output': output, 'params': params}


define('opening_range', 'P01', '開盤區間', 'price', 'PriceLevel', minutes=integer('形成分鐘', 5),
       session_open=param('日盤開盤', '08:45', 'time'), field=select('選取價格', 'high', ['high','low','mid']))
define('rolling_range', 'P02', '前 N 根高低點', 'price', 'PriceLevel', period=integer('回看根數', 20),
       basis=BASIS, lock=param('首次形成後鎖定至突破', False, 'boolean'))
define('swing', 'P03', '已確認波段高低點', 'price', 'PriceLevel', left=integer('左側根數', 2), right=integer('右側確認根數', 2),
       basis=BASIS, side=select('輸出方向', 'both', ['both', 'high', 'low']), min_turn=param('最小轉折點數', 0),
       ties=select('相同價格', 'strict', ['strict', 'latest', 'earliest']))
define('previous_day', 'P04', '前日關鍵價', 'price', 'PriceLevel')
define('day_range', 'P05', '當日截至目前高低點', 'price', 'PriceLevel')
define('support_resistance', 'P06', '自動支撐壓力區', 'price', 'PriceLevel', method=select('辨識來源', 'swing', ['swing', 'box']),
       left=integer('波段左側', 2), right=integer('波段右側', 2), period=integer('箱體回看', 20),
       tolerance=param('合併容差', 2), min_tests=integer('獨立測試次數', 2), reaction=param('每次最小反應', 3),
       mode=select('線／區域', 'zone', ['zone', 'line']), role=select('選取角色', 'both', ['both', 'support', 'resistance']),
       role_reversal=param('突破後角色互換', True, 'boolean'), max_zones=integer('保留區域上限', 50))
define('box', 'P07', '盤整箱體', 'price', 'PriceLevel', period=integer('回看根數', 20), min_width=param('最小寬度', 0),
       max_width=param('最大寬度', 100), hold=integer('至少維持根數', 3), tolerance=param('邊界容差', 2))
define('gap', 'P08', '開盤缺口', 'price', 'PriceLevel', direction=select('跳空方向', 'both', ['both', 'up', 'down']), min_gap=param('最小跳空點數', 5))
define('ma', 'P09', '移動平均', 'price', 'PriceLevel', period=integer('均線根數', 20))
define('snapshot', 'P10', '事件發生時鎖定價格', 'price', 'PriceLevel', source=SOURCE, trigger=INPUT)

define('breakout', 'E01', '價格突破', 'entry', source=SOURCE, field=FIELD, direction=DIRECTION,
       mode=select('確認方式', 'close', ['touch', 'cross', 'close', 'body']), min_break=param('最小突破點數', 0),
       confirm=integer('連續確認根數', 1), occurrence=param('第幾次突破（0=不限）', 0, 'integer'), max_chase=param('最大追價距離（0=不限）', 0))
define('retest', 'E02', '突破後回踩確認', 'entry', source=SOURCE, field=FIELD, direction=DIRECTION,
       within=integer('突破後最多等待根數', 10), tolerance=param('回踩容差', 2),
       mode=select('回踩方式', 'wick', ['wick', 'close']), confirm=select('確認 K', 'color', ['none', 'color', 'break_candle']),
       occurrence=integer('第幾次回踩', 1), invalidation=param('超越參考價失效點數', 10))
for kind, code, name, direction in [('bounce', 'E03', '支撐反彈', 'up'), ('rejection', 'E04', '壓力反轉', 'down')]:
    define(kind, code, name, 'entry', source=SOURCE, direction=select('方向', direction, ['up', 'down']), tolerance=param('觸及容差', 2),
           wick_ratio=param('影線最小占比', .4, maximum=1), reaction=param('最小反彈／回落', 3),
           confirm_break=param('等待突破確認 K 高低', True, 'boolean'), within=integer('確認有效根數', 5))
define('false_break', 'E05', '假突破反向訊號', 'entry', source=SOURCE, field=FIELD, direction=DIRECTION,
       within=integer('收回區間期限', 5), min_break=param('最小假突破幅度', 2), reverse_candle=param('要求反向 K', True, 'boolean'))
define('n_pattern', 'E06', 'N 字順勢回調', 'entry', source=SOURCE, direction=DIRECTION, min_push=param('最小推進點數', 10),
       min_retrace=param('最小回調比例', .2, maximum=1), max_retrace=param('最大回調比例', .8, maximum=1),
       max_pullback=integer('最大回調根數', 20), min_break=param('二次突破幅度', 0))
define('bos', 'E07', '結構突破 BOS', 'entry', source=SOURCE, direction=DIRECTION, min_break=param('突破幅度', 0),
       mode=select('確認方式', 'close', ['touch', 'close']), require_trend=param('要求既有趨勢', False, 'boolean'))
define('choch', 'E08', '結構反轉 CHoCH', 'entry', source=SOURCE, direction=DIRECTION, min_break=param('破壞幅度', 0),
       wait_retest=param('等待回踩', False, 'boolean'), within=integer('反轉有效根數', 10), tolerance=param('回踩容差', 2))
define('engulfing', 'E09', '吞噬 K', 'entry', direction=DIRECTION, mode=select('吞噬範圍', 'body', ['body', 'full']),
       min_body=param('最小實體點數', 1), confirm_break=param('下一根突破確認', False, 'boolean'), within=integer('確認期限', 5))
define('pinbar', 'E10', '影線反轉 K', 'entry', direction=DIRECTION, wick_ratio=param('影線最小占比', .6, maximum=1),
       max_body_ratio=param('實體最大占比', .3, maximum=1), close_ratio=param('收盤接近端點比例', .25, maximum=1), min_range=param('K 棒最小長度', 5))
define('consecutive', 'E11', '連續 K 棒', 'entry', direction=DIRECTION, count=integer('連續根數', 3), min_body=param('每根最小實體', 1),
       staircase=param('依方向逐根推進', False, 'boolean'), higher_highs=param('要求高點逐根抬高', False, 'boolean'),
       lower_lows=param('要求低點逐根降低', False, 'boolean'), min_push=param('最小總推進', 0))
define('box_break', 'E12', '箱體突破', 'entry', source=SOURCE, direction=DIRECTION, mode=select('突破確認', 'close', ['close', 'body']),
       wait_retest=param('等待回踩', False, 'boolean'), within=integer('回踩期限', 10), tolerance=param('回踩容差', 2))

define('time_filter', 'F01', '允許交易時段', 'filter', start=param('起始', '08:45', 'time'), end=param('結束', '13:40', 'time'))
define('trend_filter', 'F02/F03', 'HH/HL 或 LH/LL 趨勢', 'filter', source=SOURCE, direction=DIRECTION)
define('range_filter', 'F04', '參考區間大小', 'filter', source=SOURCE, minimum=param('最小寬度', 0), maximum=param('最大寬度', 100))
define('body_filter', 'F05', 'K 棒實體大小', 'filter', minimum=param('最小實體', 0), maximum=param('最大實體', 100))
define('distance_filter', 'F06', '距參考價格點數', 'filter', source=SOURCE, field=FIELD, minimum=param('最小距離', 0), maximum=param('最大距離', 100))
define('pullback_filter', 'F07', '回調深度比例', 'filter', source=SOURCE, direction=DIRECTION, minimum=param('最小比例', .2, maximum=1), maximum=param('最大比例', .8, maximum=1))
define('occurrence_filter', 'F08', '指定第 N 次訊號', 'filter', source=INPUT, occurrence=integer('第幾次', 1))
define('expire', 'F09/L06', '訊號有效期限', 'logic', source=INPUT, bars=integer('有效 K 棒數', 3))
define('cooldown_filter', 'F10', '停損後冷卻', 'filter', bars=integer('冷卻根數', 3))
define('daily_count_filter', 'F11', '每日交易次數限制', 'filter', maximum=integer('每日最多筆數', 3))
define('risk_distance_filter', 'F12', '停損最大距離', 'filter', source=SOURCE, direction=DIRECTION, maximum=param('最大停損距離', 50))
define('space_filter', 'F13', '最近支撐壓力空間', 'filter', source=SOURCE, direction=DIRECTION, minimum=param('最小空間', 20))
define('calendar_filter', 'F14', '星期與日期排除', 'filter', weekdays=param('排除星期（週一=0）', [], 'integer_list'), dates=param('排除日期', [], 'date_list'))

define('stop_fixed', 'S01', '固定點數停損', 'stop', 'PriceLevel', points=param('停損點數', 30))
define('stop_signal', 'S02', '訊號 K 棒停損', 'stop', 'PriceLevel', buffer=BUFFER)
define('stop_previous', 'S03', '前一根 K 棒停損', 'stop', 'PriceLevel', buffer=BUFFER)
define('stop_structure', 'S04', '波段結構停損', 'stop', 'PriceLevel', source=SOURCE, buffer=BUFFER, maximum=param('最大距離（0=不限）', 0),
       mode=select('結構類型', 'swing', ['swing', 'hl_lh']))
define('stop_zone', 'S05', '支撐壓力停損', 'stop', 'PriceLevel', source=SOURCE, buffer=BUFFER)
define('stop_range', 'S06', '區間邊界停損', 'stop', 'PriceLevel', source=SOURCE, buffer=BUFFER)
define('stop_trailing_structure', 'S07', '移動結構停損', 'stop', 'PriceLevel', source=SOURCE, buffer=BUFFER, new_extreme=param('創新高低後才更新', True, 'boolean'))
define('stop_trailing_points', 'S08', '追蹤點數停損', 'stop', 'PriceLevel', activate=param('啟動獲利點數', 20), distance=param('回撤點數', 10))
define('target_fixed', 'X01', '固定點數停利', 'target', 'PriceLevel', points=param('停利點數', 60))
define('target_rr', 'X02', '固定風險報酬比', 'target', 'PriceLevel', ratio=param('風險報酬倍數 R', 2))
define('target_reference', 'X03', '最近支撐壓力停利', 'target', 'PriceLevel', source=SOURCE, buffer=BUFFER)
define('exit_structure', 'X04', '結構失效出場', 'exit', source=SOURCE)
define('exit_reversal', 'X05', '反向反轉 K 出場', 'exit', pattern=select('型態', 'engulfing', ['engulfing', 'pinbar']))
define('exit_ma', 'X06', '移動平均出場', 'exit', period=integer('均線週期', 20), mode=select('確認方式', 'close', ['close', 'body']))
define('exit_bars', 'X07', '持倉 N 根出場', 'exit', bars=integer('持倉根數', 10))
define('exit_time', 'X08', '指定時間平倉', 'exit', time=param('強制平倉時間', '13:40', 'time'))
define('exit_failure', 'X09', '突破失敗出場', 'exit', source=SOURCE, tolerance=param('失敗點數', 0))
define('exit_n_failure', 'X10', 'N 字結構失效', 'exit', source=SOURCE)
define('exit_giveback', 'X11', '獲利回吐百分比', 'exit', activate=param('啟動獲利點數', 20), percent=param('回吐比例', .5, maximum=1))
define('exit_consecutive', 'X12', '連續反向 K 出場', 'exit', count=integer('反向根數', 3))

define('and', 'L01', 'AND 全部成立', 'logic', inputs=INPUTS)
define('or', 'L02', 'OR 任一成立', 'logic', inputs=INPUTS)
define('not', 'L03', 'NOT 排除條件', 'logic', source=INPUT)
define('sequence', 'L04', '依序 A → B → C', 'logic', inputs=INPUTS, within=integer('等待上限分鐘', 30), restart_on_a=param('新 A 重新計時', True, 'boolean'))
define('count', 'L05', '指定根數內出現 N 次', 'logic', source=INPUT, window=integer('觀察根數', 10), count=integer('成立次數', 3))
define('reset', 'L07', '成立後保持／重置', 'logic', source=INPUT, reset=INPUT)
define('delay', 'L08', '延後 N 根觸發', 'logic', source=INPUT, bars=integer('延後根數', 1))
define('event', 'L09', '條件成立邊緣事件', 'logic', 'Event', source=INPUT)
define('compare', 'C01', '收盤與價格比較', 'entry', source=SOURCE, field=FIELD, direction=DIRECTION)
define('candle', 'C02', 'K 棒方向確認', 'entry', direction=DIRECTION)
define('touch_reference', 'C03', '參考價觸及與收盤確認', 'entry', source=SOURCE, field=FIELD, direction=DIRECTION, tolerance=param('容許點數', 2))

for _kind in ('n_pattern','trend_filter','pullback_filter','bos','choch','stop_structure','stop_trailing_structure','exit_structure','exit_n_failure'):
    CATALOG[_kind]['params']['source'] = {**CATALOG[_kind]['params']['source'], 'accepts': ['swing']}
CATALOG['box_break']['params']['source'] = {**CATALOG['box_break']['params']['source'], 'accepts': ['box']}
CATALOG['stop_range']['params']['source'] = {**CATALOG['stop_range']['params']['source'], 'accepts': ['opening_range','rolling_range','box']}


def catalog():
    return list(CATALOG.values())


def make_block(kind, id, **params):
    d = CATALOG[kind]
    return {'id': id, 'type': kind, 'name': d['name'], 'enabled': True, 'timeframe': 1,
            'output': d['output'], 'params': {**{k: v['default'] for k, v in d['params'].items()}, **params}}
