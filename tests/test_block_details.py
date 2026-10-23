"""Additional hand-computed block and matching boundary cases."""
import copy
import unittest
from datetime import timedelta

from backtester.blocks import Evaluator
from backtester.catalog import make_block as b
from backtester.data import Bar, TIMEFRAMES, aggregate
from backtester.engine import run
from backtester.examples import base
from backtester.matching import Broker
from test_extended import START, candles, points, configured, fixture


def evaluate(blocks, rows, context=None):
    strategy=base('unit','unit',blocks,None)
    evaluator=Evaluator(strategy,{tf:aggregate(rows,tf) for tf in TIMEFRAMES})
    snapshots=[]
    for row in rows:
        evaluator.step(row.end,context)
        snapshots.append(copy.deepcopy(evaluator.values))
    return snapshots


class PriceAndSignalTests(unittest.TestCase):
    def test_custom_opening_time_midpoint_and_no_early_availability(self):
        rows=candles([(100,110,90,100)]*25)
        result=evaluate([b('opening_range','p',minutes=5,session_open='09:00',field='mid')],rows)
        self.assertIsNone(result[18]['p']['value'])
        self.assertEqual(result[19]['p']['value']['value'],100)
        self.assertEqual(result[19]['p']['meta']['formed_at'],'2024-02-01T09:05:00+08:00')

    def test_body_range_excludes_current(self):
        rows=candles([(100,150,50,105),(106,180,10,110),(111,500,1,115)])
        result=evaluate([b('rolling_range','p',period=2,basis='body')],rows)
        self.assertEqual(result[-1]['p']['value']['high'],110)
        self.assertEqual(result[-1]['p']['value']['low'],100)

    def test_previous_day_gap_and_day_range(self):
        rows=[Bar(START,100,105,95,102),Bar(START+timedelta(days=1),112,115,110,114),Bar(START+timedelta(days=1,minutes=1),114,116,101,103)]
        result=evaluate([b('previous_day','p'),b('gap','g',min_gap=5),b('day_range','d')],rows)
        self.assertIsNone(result[0]['g']['value'])
        self.assertEqual(result[1]['p']['value']['close'],102)
        self.assertEqual(result[1]['g']['value']['low'],102)
        self.assertAlmostEqual(result[1]['g']['meta']['fill_ratio'],.2)
        self.assertEqual(result[2]['g']['meta']['fill_ratio'],1)
        self.assertEqual(result[1]['d']['value']['high'],115)
        self.assertEqual(result[2]['d']['value']['high'],116)

    def test_pivot_ties_and_candidate_confirmation_times(self):
        rows=candles(points([100,110,110,100,99]))
        strict=evaluate([b('swing','s',left=1,right=1,ties='strict')],rows)
        self.assertFalse(any(p['kind']=='high' for p in strict[-1]['s']['meta']['pivots']))
        latest=evaluate([b('swing','s',left=1,right=1,ties='latest')],rows)
        high=next(p for p in latest[-1]['s']['meta']['pivots'] if p['kind']=='high')
        self.assertEqual(high['candidate_time'],rows[2].start.isoformat())
        self.assertEqual(high['confirmed_at'],rows[3].end.isoformat())

    def test_independent_zone_tests_do_not_double_count_pivots(self):
        rows=candles([(100,101,99,100),(100,101,98,100),(95,96,90,95),(96,99,94,98),(98,101,97,100),(92,94,89,93),(96,99,96,98),(98,100,97,99),(99,101,98,100)])
        result=evaluate([b('support_resistance','z',min_tests=2,tolerance=2,reaction=3)],rows)
        zone=next(z for z in result[4]['z']['meta']['zones'] if z['role']=='support')
        self.assertEqual(zone['tests'],1)
        self.assertIsNone(result[4]['z']['value'])
        matching=[z for z in result[6]['z']['meta']['zones'] if z['role']=='support' and abs(z['center']-90)<=2]
        self.assertEqual(matching[0]['tests'],2)
        self.assertEqual(matching[0]['confirmed_at'],rows[6].end.isoformat())
        later=next(z for z in result[-1]['z']['meta']['zones'] if z['id']==matching[0]['id'])
        self.assertEqual(later['tests'],2)

    def test_breakout_locks_reference_for_multiple_confirmation_bars(self):
        rows=candles([(100,101,99,100)]*2+[(100,106,99,105),(105,108,104,107)])
        result=evaluate([b('rolling_range','p',period=2),b('breakout','e',source='p',confirm=2)],rows)
        self.assertFalse(result[2]['e']['value'])
        self.assertTrue(result[3]['e']['value'])
        self.assertIn('參考=101',result[3]['e']['reason'])

    def test_body_breakout_and_nth_breakout(self):
        rows=candles([(100,101,99,100)]*5+[(100,106,99,105),(104,108,103,107),(100,101,99,100),(100,108,99,106)])
        blocks=[b('opening_range','p'),b('breakout','body',source='p',mode='body'),b('breakout','second',source='p',occurrence=2)]
        result=evaluate(blocks,rows)
        self.assertFalse(result[5]['body']['value']);self.assertTrue(result[6]['body']['value'])
        self.assertFalse(result[5]['second']['value']);self.assertTrue(result[8]['second']['value'])

    def test_touch_does_not_use_an_opening_range_before_it_exists(self):
        rows=candles([(100,101,99,100)]*6)
        result=evaluate([b('opening_range','p'),b('breakout','e',source='p',mode='touch')],rows)
        self.assertFalse(result[4]['e']['value']);self.assertTrue(result[5]['e']['value'])

    def test_box_breakout_can_retest_after_box_is_invalidated(self):
        rows=candles([(100,101,99,100)]*5+[(100,106,99,105),(105,106,100,103),(103,105,102,104)])
        result=evaluate([b('box','p',period=3,hold=2,max_width=5),b('box_break','e',source='p',wait_retest=True,tolerance=2)],rows)
        self.assertFalse(result[5]['e']['value']);self.assertTrue(result[6]['e']['value'])

    def test_choch_breaks_a_previously_confirmed_downtrend(self):
        values=[120,119,110,115,120,118,114,105,110,115,113,109,100,105,110,108,104,95,100,105,110,116,112]
        result=evaluate([b('swing','s'),b('choch','c',source='s',direction='up')],candles(points(values)))
        self.assertTrue(result[21]['c']['value'])
        self.assertFalse(any(r['c']['value'] for r in result[:21]))

    def test_engulfing_and_pinbar_constraints(self):
        rows=candles([(105,106,99,100),(99,107,98,106),(105,110,90,106)])
        result=evaluate([b('engulfing','e',direction='up'),b('pinbar','p',direction='up')],rows)
        self.assertTrue(result[1]['e']['value']);self.assertTrue(result[2]['p']['value'])


class MatchingRuleTests(unittest.TestCase):
    def plan(self):
        return {'direction':1,'side':'long','values':{'p':{'value':{'low':92,'high':110},'meta':{'pivots':[{'kind':'low','price':88},{'kind':'low','price':92}]}}},
                'signal_bar':Bar(START,99,105,95,101),'previous_bar':Bar(START-timedelta(minutes=1),96,100,90,99),
                'block_id':'e','reason':'人工訊號','signal_id':'test-event','at':START+timedelta(minutes=1)}

    def strategy(self,rule):
        source=b('opening_range','p');entry=b('candle','e')
        s=base('broker','broker',[source,entry,rule],'e',stop=[rule['id']])
        s['costs'].update(point_value=10,commission=0,tax_rate=0,tax_fixed=0,slippage=0)
        return s

    def test_six_initial_stop_bases(self):
        expected=[('stop_fixed',{'points':10},90),('stop_signal',{'buffer':1},94),('stop_previous',{'buffer':1},89),
                  ('stop_structure',{'source':'p','buffer':1},91),('stop_zone',{'source':'p','buffer':1},91),('stop_range',{'source':'p','buffer':1},91)]
        for kind,params,price in expected:
            with self.subTest(kind=kind):
                broker=Broker(self.strategy(b(kind,'s',**params)))
                self.assertTrue(broker.enter(self.plan(),Bar(START+timedelta(minutes=1),100,105,98,102)))
                self.assertEqual(broker.position['stop'],price)

    def test_rr_and_reference_target(self):
        for rule,expected in [(b('target_fixed','t',points=20),120),(b('target_rr','t',ratio=2),120),(b('target_reference','t',source='p',buffer=1),109)]:
            s=self.strategy(b('stop_fixed','s',points=10));s['blocks'].append(rule);s['risk']['long']['target_blocks']=['t'];broker=Broker(s)
            self.assertTrue(broker.enter(self.plan(),Bar(START,100,101,99,100)));self.assertEqual(broker.position['target'],expected)

    def test_trailing_points_updates_next_bar_and_never_loosens(self):
        s=self.strategy(b('stop_trailing_points','s',activate=10,distance=5));broker=Broker(s)
        broker.enter(self.plan(),Bar(START,100,101,99,100))
        self.assertIsNone(broker.position['stop'])
        bar=Bar(START+timedelta(minutes=1),100,115,98,112)
        self.assertFalse(broker.protect(bar));broker.update_after_close(bar,{})
        self.assertEqual(broker.position['stop'],110)
        broker.update_after_close(Bar(bar.end,112,113,111,112),{})
        self.assertEqual(broker.position['stop'],110)
        self.assertTrue(broker.protect(Bar(bar.end+timedelta(minutes=1),108,109,105,106)))
        self.assertEqual(broker.trades[0]['exit_price'],108)

    def test_signal_expiry_does_not_reuse_one_event_after_stops(self):
        s=base('expire','expire',[b('candle','a'),b('event','event',source='a'),b('expire','entry',source='event',bars=6)],'entry')
        s['limits']['entry_start']='08:45';s['risk']={'stop_points':1};s['costs'].update(slippage=0)
        result=run(candles([(100,103,98,102)]*10),s)
        self.assertEqual(len(result['trades']),1)
        ids=[v['event_id'] for v in result['signals']];self.assertEqual(len(ids),len(set(ids)))

    def test_opening_gap_cannot_bypass_maximum_chase(self):
        s=configured(0);s['blocks'][1]['params']['max_chase']=5
        rows=fixture(0);rows[6]=Bar(rows[6].start,120,125,118,122)
        result=run(rows,s)
        self.assertEqual(result['trades'],[])
        self.assertTrue(any('追價距離' in w for w in result['warnings']))

    def test_stop_distance_weekday_and_date_limits(self):
        s=configured(0);s['limits']['max_stop_distance']=5
        self.assertEqual(run(fixture(0),s)['trades'],[])
        s=configured(0);s['limits']['excluded_weekdays']=[3]
        self.assertEqual(run(fixture(0),s)['trades'],[])
        s['limits']['excluded_weekdays']=[];s['limits']['excluded_dates']=['2024-02-01']
        self.assertEqual(run(fixture(0),s)['trades'],[])


if __name__=='__main__':unittest.main()
