import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backtester.data import Bar, TAIPEI, aggregate, parse_csv
from backtester.engine import canonical, metrics, run
from backtester.server import create_server
from backtester.store import Store
from backtester.strategy import Evaluator, templates, validate


BASE = datetime(2026, 10, 19, 8, 45, tzinfo=TAIPEI)


def bars(values, start=BASE):
    return [Bar(start + timedelta(minutes=i), *v) for i, v in enumerate(values)]


def flat(n, price=100):
    return [(price, price+1, price-1, price)] * n


def settings_strategy():
    s = copy.deepcopy(templates()[0])
    s['costs'] = {'point_value': 10, 'commission': 0, 'tax_mode': 'notional', 'tax_rate': 0,
                  'tax_fixed': 0, 'slippage': 0, 'initial_capital': 10000}
    s['limits']['entry_start'] = '08:45'
    s['risk'] = {'stop_points': 10, 'target_points': 20}
    return s


def simple_block(id, kind, params, tf=1):
    return {'id': id, 'type': kind, 'params': params, 'name': id, 'enabled': True,
            'timeframe': tf, 'output': 'Event' if kind == 'event' else 'PriceLevel' if kind in ('ma','swing','rolling_range','opening_range','snapshot') else 'Condition'}


class DataTests(unittest.TestCase):
    def test_invalid_timezone_and_nondecimal_prices_rejected(self):
        for zone in ('+25:00','+08:99'):
            _,report=parse_csv(f'datetime,open,high,low,close\n2024-02-01 08:45:00{zone},100,101,99,100'.encode())
            self.assertTrue(report['errors'])
        for number in ('0x64','"1,00"','1_00'):
            _,report=parse_csv(f'datetime,open,high,low,close\n2024-02-01 08:45,{number},101,99,100'.encode())
            self.assertTrue(report['errors'])
    def test_big5_chinese_split_datetime_like_user_csv(self):
        text='日期,時間,開盤價,最高價,最低價,收盤價,成交量\r\n2024/2/1,08:45:00,17978,17978,17950,17973,3537\r\n2024/2/1,08:46:00,17973,17985,17972,17976,1645'
        for encoding in ('cp950','utf-8-sig','utf-16'):
            with self.subTest(encoding=encoding):
                data,report=parse_csv(text.encode(encoding))
                self.assertEqual(report['errors'],[])
                self.assertEqual(len(data),2)
                self.assertEqual(data[0].start.isoformat(),'2024-02-01T08:45:00+08:00')
                self.assertEqual(data[0].close,17973)
                self.assertEqual(data[0].volume,3537)

    def test_packed_date_time_chinese_mapping_and_quoted_numbers(self):
        text='日期;時間;開盤價;最高價;最低價;收盤價\n20240201;084500;"17,978";"17,978";"17,950";"17,973"'
        data,report=parse_csv(text.encode())
        self.assertEqual(report['errors'],[])
        self.assertEqual(data[0].close,17973)
        self.assertEqual(data[0].start.isoformat(),'2024-02-01T08:45:00+08:00')

    def test_mapping_and_missing_volume(self):
        raw = b't,o,h,l,c\n2026-10-19 08:45,100,102,99,101\n'
        rows, report = parse_csv(raw, dict(zip(['datetime','open','high','low','close'], ['t','o','h','l','c'])))
        self.assertEqual(report['errors'], [])
        self.assertIsNone(rows[0].volume)
        self.assertEqual(rows[0].start.utcoffset(), timedelta(hours=8))

    def test_duplicates_unsorted_and_invalid_prices(self):
        raw = b'datetime,open,high,low,close\n2026-10-19 08:46,100,101,99,100\n2026-10-19 08:45,100,101,99,100\n2026-10-19 08:46,100,101,99,100\n2026-10-19 08:47,100,90,99,100\n'
        _, r = parse_csv(raw)
        self.assertTrue(any('重複' in e for e in r['errors']))
        self.assertTrue(any('排序' in e for e in r['errors']))
        self.assertTrue(any('OHLC' in e for e in r['errors']))

    def test_nan_infinity_and_seconds_rejected(self):
        for value in ('nan','inf','-1'):
            _, r = parse_csv(f'datetime,open,high,low,close\n2026-10-19 08:45,{value},110,90,100'.encode())
            self.assertTrue(r['errors'])
        _, r = parse_csv(b'datetime,open,high,low,close\n2026-10-19 08:45:01,100,110,90,100')
        self.assertTrue(r['errors'])

    def test_gap_night_and_partial_aggregation(self):
        raw = b'datetime,open,high,low,close\n2026-10-19 08:45,100,101,99,100\n2026-10-19 08:47,100,101,99,100\n2026-10-19 15:00,100,101,99,100'
        rows, r = parse_csv(raw)
        self.assertEqual(len(rows), 3)
        self.assertEqual(r['night_rows'], 1)
        self.assertEqual(r['missing_minutes'], ['2026-10-19T08:46:00+08:00'])
        self.assertEqual(aggregate(rows, 5), [])
        self.assertEqual(len(aggregate(rows, 1)), 2)

    def test_aggregation_session_anchor(self):
        rows = bars([(100+i,102+i,99+i,101+i,10) for i in range(15)])
        five = aggregate(rows, 5)
        self.assertEqual(len(five), 3)
        self.assertEqual((five[0].open,five[0].high,five[0].low,five[0].close,five[0].volume),(100,106,99,105,50))
        self.assertEqual(five[0].end, BASE+timedelta(minutes=5))
        self.assertEqual(len(aggregate(rows,15)),1)


class BlockTests(unittest.TestCase):
    def test_templates_validate(self):
        for s in templates():
            self.assertTrue(validate(s))

    def test_types_cycles_disabled_duplicate_rejected(self):
        s = settings_strategy()
        s['entries']['long'] = 'range'
        with self.assertRaisesRegex(ValueError, 'Condition'):
            validate(s)
        s = settings_strategy()
        s['blocks'] += [simple_block('a','and',{'inputs':['b','long']}),simple_block('b','and',{'inputs':['a','short']})]
        with self.assertRaisesRegex(ValueError, '循環'):
            validate(s)
        s = settings_strategy()
        s['blocks'][0]['enabled'] = False
        with self.assertRaisesRegex(ValueError, '未啟用'):
            validate(s)
        s = settings_strategy()
        s['blocks'].append(copy.deepcopy(s['blocks'][0]))
        with self.assertRaisesRegex(ValueError, '唯一'):
            validate(s)

    def test_rolling_excludes_current(self):
        s = settings_strategy()
        s['blocks'] = [simple_block('range','rolling_range',{'period':2})] + s['blocks'][1:]
        rows = bars(flat(2)+[(100,500,99,110)])
        e = Evaluator(s,{tf:aggregate(rows,tf) for tf in (1,5,15)})
        for b in rows:
            e.step(b.end)
        self.assertEqual(e.values['range']['value']['high'],101)
        self.assertTrue(e.values['long']['value'])

    def test_opening_range_unavailable_until_close(self):
        s = settings_strategy(); rows=bars(flat(5))
        e=Evaluator(s,{tf:aggregate(rows,tf) for tf in (1,5,15)})
        e.step(rows[3].end)
        self.assertIsNone(e.values['range']['value'])
        e.step(rows[4].end)
        self.assertEqual(e.values['range']['value'],{'high':101,'low':99})

    def test_swing_right_confirmation(self):
        s=settings_strategy();s['blocks']=[simple_block('range','swing',{'left':1,'right':2})]+s['blocks'][1:]
        rows=bars([(100,101,99,100),(100,110,98,100),(100,102,99,100),(100,103,99,100)])
        e=Evaluator(s,{tf:aggregate(rows,tf) for tf in (1,5,15)})
        for b in rows[:3]: e.step(b.end)
        self.assertIsNone(e.values['range']['value'])
        e.step(rows[3].end)
        self.assertEqual(e.values['range']['value'],{'high':110,'low':98})

    def test_high_timeframe_not_available_early(self):
        s=settings_strategy();s['blocks']=[simple_block('range','ma',{'period':1},5),simple_block('long','compare',{'source':'range','field':'value','direction':'up'})];s['entries']['short']=None
        rows=bars([(100,102+i,99,101+i) for i in range(6)])
        e=Evaluator(s,{tf:aggregate(rows,tf) for tf in (1,5,15)})
        for b in rows[:4]: e.step(b.end)
        self.assertNotIn('range',e.values)
        e.step(rows[4].end)
        self.assertEqual(e.values['range']['at'],BASE+timedelta(minutes=5))
        self.assertEqual(e.values['range']['value'],{'value':105})
        e.step(rows[5].end)
        self.assertEqual(e.values['range']['value'],{'value':105})

    def test_sequence_strictly_after_and_event_edge(self):
        s=settings_strategy();s['blocks']=[simple_block('a','candle',{'direction':'up'}),simple_block('b','candle',{'direction':'up'}),simple_block('seq','sequence',{'inputs':['a','b'],'within':10}),simple_block('edge','event',{'source':'a'})];s['entries']={'long':'seq','short':None}
        rows=bars([(100,102,99,101)]*3)
        e=Evaluator(s,{tf:aggregate(rows,tf) for tf in (1,5,15)})
        e.step(rows[0].end)
        self.assertFalse(e.values['seq']['value'])
        self.assertTrue(e.values['edge']['value'])
        e.step(rows[1].end)
        # A is a newly confirmed true condition again: simultaneous A/B cannot satisfy A then B.
        self.assertFalse(e.values['seq']['value'])
        self.assertFalse(e.values['edge']['value'])

    def test_sequence_timeout(self):
        s=settings_strategy();s['blocks']=[simple_block('a','candle',{'direction':'up'}),simple_block('b','candle',{'direction':'down'}),simple_block('seq','sequence',{'inputs':['a','b'],'within':1})];s['entries']={'long':'seq','short':None}
        rows=bars([(100,102,99,101),(100,101,99,100),(100,101,98,99)])
        e=Evaluator(s,{tf:aggregate(rows,tf) for tf in (1,5,15)})
        for b in rows:e.step(b.end)
        self.assertFalse(e.values['seq']['value'])

    def test_or_and_boolean_outputs(self):
        s=settings_strategy();s['blocks']=[simple_block('a','candle',{'direction':'up'}),simple_block('b','candle',{'direction':'down'}),simple_block('any','or',{'inputs':['a','b']}),simple_block('all','and',{'inputs':['a','b']})];s['entries']={'long':'any','short':None}
        rows=bars([(100,102,99,101)])
        e=Evaluator(s,{tf:aggregate(rows,tf) for tf in (1,5,15)})
        e.step(rows[0].end)
        self.assertTrue(e.values['any']['value'])
        self.assertFalse(e.values['all']['value'])

    def test_future_append_does_not_change_past_signals(self):
        original=bars(flat(5)+[(100,105,99,104),(104,107,103,106),(106,107,104,105)])
        future=original+bars([(105,1000,1,999)]*20,original[-1].end)
        for s in templates():
            first=run(original,s)['signals']
            second=[v for v in run(future,s)['signals'] if v['trigger_time']<=original[-1].end.isoformat()]
            self.assertEqual(first,second,s['strategy_id'])


class ExecutionTests(unittest.TestCase):
    def entry_rows(self, last):
        return bars(flat(5)+[(100,105,99,104),last,(105,106,104,105)])

    def test_signal_close_and_next_open(self):
        s=settings_strategy();r=run(self.entry_rows((106,108,105,107)),s)
        t=r['trades'][0]
        self.assertEqual(t['entry_time'],'2026-10-19T08:51:00+08:00')
        self.assertEqual(t['entry_price'],106)
        signal=next(v for v in r['signals'] if v['event_id']==t['signal_id'])
        self.assertEqual(signal['trigger_time'],t['entry_time'])
        self.assertEqual(signal['block_id'],'long')

    def test_stop_first_collision(self):
        s=settings_strategy();r=run(self.entry_rows((104,130,90,104)),s)
        t=r['trades'][0]
        self.assertEqual(t['exit_price'],94)
        self.assertTrue(t['ambiguous_order'])
        self.assertEqual(t['net_pnl'],-100)

    def test_gap_stop_uses_open_plus_slippage(self):
        s=settings_strategy();s['costs']['slippage']=1
        rows=bars(flat(5)+[(100,105,99,104),(104,106,103,105),(80,85,75,82)])
        t=run(rows,s)['trades'][0]
        self.assertEqual(t['entry_price'],105)
        self.assertEqual(t['stop'],95)
        self.assertEqual(t['exit_price'],79)
        self.assertIn('跳空',t['exit_reason'])

    def test_target_and_short(self):
        s=settings_strategy();t=run(self.entry_rows((104,125,100,124)),s)['trades'][0]
        self.assertEqual(t['exit_price'],124)
        self.assertFalse(t['ambiguous_order'])
        rows=bars(flat(5)+[(100,101,95,96),(95,96,70,75),(75,76,74,75)])
        t=run(rows,s)['trades'][0]
        self.assertEqual(t['side'],'short')
        self.assertEqual(t['exit_price'],75)
        self.assertEqual(t['net_pnl'],200)

    def test_fees_taxes_slippage_both_sides(self):
        s=settings_strategy();s['costs'].update(commission=2,tax_rate=.001,slippage=1)
        t=run(self.entry_rows((104,106,103,105)),s)['trades'][0]
        self.assertEqual(t['entry_price'],105)
        self.assertEqual(t['exit_price'],104)
        self.assertAlmostEqual(t['cost'],4+105*10*.001+104*10*.001)
        self.assertAlmostEqual(t['net_pnl'],-10-t['cost'])
        self.assertEqual(t['slippage_cost'],20)
        s['costs'].update(tax_mode='fixed',tax_fixed=3)
        self.assertEqual(run(self.entry_rows((104,106,103,105)),s)['trades'][0]['cost'],10)

    def test_no_reversal_on_exit_bar(self):
        s=settings_strategy();s['risk']['stop_points']=2
        rows=bars(flat(5)+[(100,105,99,104),(104,105,95,96),(96,97,94,95),(95,96,94,95)])
        r=run(rows,s)
        self.assertEqual(len(r['trades']),1)
        self.assertEqual(r['trades'][0]['side'],'long')

    def test_day_end_and_no_overnight_or_night_execution(self):
        s=settings_strategy()
        rows=self.entry_rows((104,106,103,105))
        rows+=bars([(105,999,1,500)],BASE.replace(hour=15,minute=0))
        rows+=bars(flat(5),BASE+timedelta(days=1))
        r=run(rows,s)
        self.assertEqual(len(r['trades']),1)
        self.assertEqual(r['trades'][0]['exit_time'],'2026-10-19T08:53:00+08:00')
        self.assertTrue(all('15:00' not in p['time'] for p in r['equity']))

    def test_end_bar_signal_not_filled_next_day(self):
        s=settings_strategy();rows=bars(flat(5)+[(100,105,99,104)])+bars(flat(5),BASE+timedelta(days=1))
        self.assertEqual(run(rows,s)['trades'],[])

    def test_date_range_and_reproducibility(self):
        rows=self.entry_rows((104,106,103,105));s=settings_strategy()
        self.assertEqual(canonical(run(rows,s)),canonical(run(rows,s)))
        with self.assertRaisesRegex(ValueError,'沒有'):
            run(rows,s,{'start':'2026-10-20'})
        with self.assertRaisesRegex(ValueError,'晚於'):
            run(rows,s,{'start':'2026-10-21','end':'2026-10-20'})

    def test_ma_exit_next_open(self):
        s=copy.deepcopy(templates()[1]);s['costs']=settings_strategy()['costs'];s['risk']['stop_points']=100
        rows=bars(flat(20)+[(100,106,99,105),(105,106,95,96),(95,96,93,94),(94,95,93,94)])
        t=run(rows,s)['trades'][0]
        self.assertEqual(t['entry_price'],105)
        self.assertEqual(t['exit_time'],'2026-10-19T09:07:00+08:00')
        self.assertEqual(t['exit_price'],95)
        self.assertIn('MA20',t['exit_reason'])

    def test_swing_structure_entry_and_stop(self):
        s=copy.deepcopy(templates()[2]);s['costs']=settings_strategy()['costs']
        rows=bars([(100,101,99,100),(100,102,98,100),(100,110,90,100),(100,103,97,100),(100,102,98,100),(100,112,99,111),(112,113,89,100),(100,101,99,100)])
        t=run(rows,s)['trades'][0]
        self.assertEqual(t['entry_time'],'2026-10-19T08:51:00+08:00')
        self.assertEqual(t['stop'],90)
        self.assertEqual(t['exit_price'],90)

    def test_retest_locks_broken_level_waits_then_candle(self):
        s=copy.deepcopy(templates()[3]);s['costs']=settings_strategy()['costs']
        rows=bars(flat(20)+[(100,106,99,105),(105,106,104,105),(105,106,101,103),(103,105,102,104),(104,105,103,104)])
        r=run(rows,s)
        self.assertEqual(len(r['trades']),1)
        t=r['trades'][0]
        # The red retest candle at 09:07 cannot enter. The following green candle can.
        self.assertEqual(t['entry_time'],'2026-10-19T09:09:00+08:00')
        self.assertIn('先突破後回踩',t['entry_reason'])

    def test_event_is_not_reused(self):
        s=settings_strategy();s['blocks']=[simple_block('up','candle',{'direction':'up'}),simple_block('edge','event',{'source':'up'})];s['entries']={'long':'edge','short':None};s['risk']={'stop_points':1,'target_points':1}
        rows=bars([(100,103,98,102)]*10)
        r=run(rows,s)
        self.assertEqual(len(r['trades']),1)
        self.assertEqual(len({v['event_id'] for v in r['signals']}),len(r['signals']))

    def test_drawdown_includes_initial_and_mark_to_market(self):
        m=metrics([], [{'equity':900},{'equity':1200},{'equity':800}],1000)
        self.assertEqual(m['max_drawdown'],400)
        self.assertAlmostEqual(m['max_drawdown_pct'],1/3)
        self.assertIsNone(m['profit_factor'])

    def test_time_limits_daily_limit_and_multitimeframe_execution(self):
        s=settings_strategy();s['blocks']=[simple_block('long','candle',{'direction':'up'},5)];s['entries']={'long':'long','short':None};s['risk']={'stop_points':1,'target_points':1}
        s['limits']['max_trades_per_day']=1
        rows=bars([(100,103,98,102)]*20)
        r=run(rows,s)
        self.assertEqual(len(r['trades']),1)
        self.assertEqual(r['trades'][0]['entry_time'],'2026-10-19T08:50:00+08:00')
        s['limits']['entry_start']='09:00'
        t=run(rows,s)['trades'][0]
        self.assertEqual(t['entry_time'],'2026-10-19T09:00:00+08:00')
        s['limits']['entry_end']='09:00'
        with self.assertRaises(ValueError):run(rows,s)

    def test_short_structure_and_short_gap_stop(self):
        s=copy.deepcopy(templates()[2]);s['costs']=settings_strategy()['costs']
        original=flat(2)+[(100,110,90,100),(100,103,97,100),(100,102,98,100),(100,112,99,111),(112,113,89,100),(100,101,99,100)]
        inverse=[(200-o,200-l,200-h,200-c) for o,h,l,c in original]
        t=run(bars(inverse),s)['trades'][0]
        self.assertEqual(t['side'],'short')
        self.assertEqual(t['stop'],110)
        self.assertEqual(t['exit_price'],110)
        s=settings_strategy();s['costs']['slippage']=1
        rows=bars(flat(5)+[(100,101,95,96),(95,96,94,95),(120,125,115,122)])
        t=run(rows,s)['trades'][0]
        self.assertEqual(t['entry_price'],94)
        self.assertEqual(t['exit_price'],121)

    def test_metrics_net_classification_and_streaks(self):
        trades=[{'side':'long' if i%2==0 else 'short','net_pnl':p,'exit_time':'2026-10-19T09:00:00+08:00','cost':2,'slippage_cost':0} for i,p in enumerate([100,-40,-60,0,50,-20])]
        m=metrics(trades,[{'equity':10030}],10000)
        self.assertEqual(m['net_pnl'],30)
        self.assertEqual((m['gross_profit'],m['gross_loss']),(150,120))
        self.assertEqual(m['profit_factor'],1.25)
        self.assertEqual(m['longest_loss_streak'],2)
        self.assertEqual(m['monthly_pnl'],{'2026-10':30})
        self.assertAlmostEqual(m['win_rate'],2/6)


class PersistenceTests(unittest.TestCase):
    def test_imported_strategy_accepts_equivalent_optional_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'versions.db')
            s=settings_strategy();s['version']=1
            store.save_strategy(s)
            s['version']='1';s['risk']['structure_source']=None
            store.save_strategy(s)
            self.assertEqual(len(store.strategies()),1)
            self.assertEqual(store.strategies()[0]['version'],1)
            s['risk']['stop_points']=20
            with self.assertRaisesRegex(ValueError,'版本'):
                store.save_strategy(s)
    def test_sqlite_roundtrip_version_guard_and_stable_run_id(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'test.db')
            raw=b'datetime,open,high,low,close\n2026-10-19 08:45,100,101,99,100'
            ds=store.import_data('test.csv',raw)
            data,report=store.dataset(ds['id'])
            s=settings_strategy();store.save_strategy(s)
            r=run(data,s);id=store.save_run(ds['id'],r)
            self.assertEqual(store.save_run(ds['id'],r),id)
            self.assertEqual(store.result(id),r)
            self.assertEqual(len(store.runs()),1)
            s['costs']['commission']=5
            with self.assertRaisesRegex(ValueError,'版本'):
                store.save_strategy(s)
            s['version']='1.1';store.save_strategy(s)
            self.assertEqual(len(store.strategies()),2)
            self.assertEqual(len(store.datasets()),1)

    def test_invalid_import_is_preserved_but_not_tradable(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'test.db');ds=store.import_data('bad.csv',b'a,b\n1,2')
            self.assertTrue(ds['report']['errors'])
            with self.assertRaisesRegex(ValueError,'錯誤'):
                store.dataset(ds['id'])


class APITests(unittest.TestCase):
    def test_browser_workflow_and_restart_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'test.db';server=create_server(port=0,db_path=db)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            root=f'http://127.0.0.1:{server.server_port}'
            def req(path,body=None):
                request=Request(root+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
                with urlopen(request) as response:return json.load(response)
            try:
                with urlopen(root+'/') as response:self.assertIn('裸 K'.encode(),response.read())
                self.assertEqual(req('/api/health')['status'],'ok')
                s=req('/api/templates')[0]
                raw='datetime,open,high,low,close\n'+'\n'.join(f'{b.start.isoformat()},{b.open},{b.high},{b.low},{b.close}' for b in bars(flat(5)+[(100,106,99,105),(105,107,104,106),(106,108,105,107)]))
                ds=req('/api/import',{'name':'人工.csv','csv':raw})
                body={'dataset_id':ds['id'],'strategy':s,'settings':{}}
                r=req('/api/run',body)
                self.assertEqual(r['metrics']['trade_count'],1)
                self.assertEqual(req('/api/run',body)['id'],r['id'])
                self.assertEqual(req('/api/runs/'+r['id'])['trades'],r['trades'])
                self.assertEqual(len(req('/api/runs')),1)
                bad=Request(root+'/api/import',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://other.example'})
                with self.assertRaises(HTTPError) as e:urlopen(bad)
                self.assertEqual(e.exception.code,403)
            finally:
                server.shutdown();server.server_close();thread.join()
            restored=Store(db)
            self.assertEqual(restored.result(r['id'])['trades'],r['trades'])


if __name__ == '__main__':
    unittest.main()
