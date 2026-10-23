"""Eight acceptance strategies, composed from the same editable catalog blocks."""
from .catalog import make_block


def base(id, name, blocks, long, short=None, stop=None, target=None, exits=None):
    return {'schema_version': 2, 'strategy_id': id, 'version': '1.0', 'name': name, 'instrument': 'TX',
            'timeframe': 1, 'direction': 'both', 'quantity': 1, 'blocks': blocks,
            'entries': {'long': long, 'short': short}, 'exits': exits or {'long': [], 'short': []},
            'risk': {'long': {'stop_blocks': stop or [], 'target_blocks': target or []},
                     'short': {'stop_blocks': stop or [], 'target_blocks': target or []}},
            'limits': {'entry_start': '08:50', 'entry_end': '13:40', 'force_close': '13:45',
                       'max_trades_per_day': 10, 'daily_max_loss': 0, 'cooldown_bars': 0,
                       'excluded_weekdays': [], 'excluded_dates': [], 'max_stop_distance': 0, 'min_space': 0},
            'execution': {'entry': 'next_open', 'collision': 'stop_first', 'valid_bars': 3},
            'costs': {'point_value': 200, 'commission': 50, 'tax_mode': 'notional', 'tax_rate': .00002,
                      'tax_fixed': 0, 'slippage': 1, 'initial_capital': 1000000}}


def templates():
    b = make_block
    opening = [b('opening_range', 'range', minutes=5),
               b('breakout', 'long', source='range', field='high', direction='up'),
               b('breakout', 'short', source='range', field='low', direction='down'),
               b('stop_fixed', 'stop', points=30)]
    fixed = base('v1-opening-fixed', '開盤 5 分突破＋固定停損', opening, 'long', 'short', ['stop'])
    ma = base('v1-opening-ma', '開盤 5 分突破＋MA20 出場', opening+[b('exit_ma', 'ma-exit', period=20)],
              'long', 'short', ['stop'], exits={'long': ['ma-exit'], 'short': ['ma-exit']})
    n = base('v1-hh-hl', 'HH／HL 回調進場＋結構停損',
             [b('swing', 'swing'), b('n_pattern', 'long-n', source='swing', direction='up', min_push=10),
              b('n_pattern', 'short-n', source='swing', direction='down', min_push=10),
              b('trend_filter', 'long-trend', source='swing', direction='up'),
              b('trend_filter', 'short-trend', source='swing', direction='down'),
              b('and', 'long', inputs=['long-n', 'long-trend']), b('and', 'short', inputs=['short-n', 'short-trend']),
              b('stop_structure', 'stop', source='swing', buffer=1)], 'long', 'short', ['stop'])
    bounce = base('v1-support-bounce', '支撐反彈＋確認 K 進場',
                  [b('swing', 'support', side='low'), b('bounce', 'long', source='support'),
                   b('stop_zone', 'stop', source='support', buffer=2)], 'long', stop=['stop'])
    retest = base('v1-break-retest', '壓力突破後回踩進場',
                  [b('rolling_range', 'pressure', period=20), b('retest', 'long', source='pressure', field='high', direction='up'),
                   b('stop_fixed', 'stop', points=30)], 'long', stop=['stop'])
    false_break = base('v1-false-break', '假突破反向進場',
                       [b('opening_range', 'range'), b('false_break', 'short', source='range', field='high', direction='up'),
                        b('false_break', 'long', source='range', field='low', direction='down'),
                        b('stop_fixed', 'stop', points=30)], 'long', 'short', ['stop'])
    box = base('v1-box-break', '盤整箱體突破進場',
               [b('box', 'box', period=10, hold=3, max_width=30), b('box_break', 'long', source='box', direction='up'),
                b('box_break', 'short', source='box', direction='down'), b('stop_range', 'stop', source='box', buffer=1)],
               'long', 'short', ['stop'])
    trailing = base('v1-swing-trailing', '波段高低點突破＋移動停損',
                    [b('swing', 'swing'), b('bos', 'long', source='swing', direction='up'),
                     b('bos', 'short', source='swing', direction='down'),
                     b('stop_trailing_structure', 'stop', source='swing', buffer=1, new_extreme=True)],
                    'long', 'short', ['stop'])
    return [fixed, ma, n, bounce, retest, false_break, box, trailing]
