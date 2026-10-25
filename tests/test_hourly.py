"""Hourly aggregation and causal higher-timeframe permission boundaries."""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from backtester.api import create_app
from backtester.blocks import Evaluator
from backtester.catalog import make_block as b
from backtester.data import Bar, TIMEFRAMES, aggregate
from backtester.examples import base
from backtester.runner import ENGINE_VERSION
from test_extended import START


def minutes(count):
    return [Bar(START+timedelta(minutes=i),100+i,102+i,99+i,101+i,1) for i in range(count)]


class HourlyTests(unittest.TestCase):
    def test_session_anchor_ohlcv_and_early_close_tail(self):
        full=aggregate(minutes(300),60)
        self.assertEqual(len(full),5)
        self.assertEqual(full[0].start,START)
        self.assertEqual(full[0].end,START+timedelta(hours=1))
        self.assertEqual((full[0].open,full[0].high,full[0].low,full[0].close,full[0].volume),(100,161,99,160,60))
        early=aggregate(minutes(285),60)
        self.assertEqual(len(early),4)
        self.assertEqual(early[-1].end,START+timedelta(hours=4))

    def test_missing_minute_or_contract_change_invalidates_its_hour(self):
        rows=minutes(300)
        missing=aggregate(rows[:30]+rows[31:],60)
        self.assertEqual(len(missing),4)
        self.assertEqual(missing[0].start,START+timedelta(hours=1))
        mixed=[Bar(x.start,x.open,x.high,x.low,x.close,contract='A' if i<30 else 'B') for i,x in enumerate(rows)]
        self.assertEqual(len(aggregate(mixed,60)),4)

    def test_hour_is_not_available_one_minute_before_completion(self):
        block=b('candle','hour',direction='up');block['timeframe']=60
        s=base('hour','hour',[block],None);rows=minutes(120)
        e=Evaluator(s,{tf:aggregate(rows,tf) for tf in TIMEFRAMES})
        e.step(START+timedelta(minutes=59));self.assertNotIn('hour',e.values)
        e.step(START+timedelta(minutes=60))
        self.assertTrue(e.values['hour']['value'])
        self.assertEqual(e.values['hour']['at'],START+timedelta(minutes=60))

    def test_hourly_hh_hl_waits_for_right_confirmation_and_never_backfills(self):
        rows=[]
        for i,price in enumerate([100,120,110,130,120,140,130]):
            start=START+timedelta(days=i//5,minutes=(i%5)*60)
            rows.extend(Bar(start+timedelta(minutes=j),price,price+1,price-1,price+.1) for j in range(60))
        swing=b('swing','macro',left=1,right=1);swing['timeframe']=60
        permission=b('trend_filter','permission',source='macro',direction='up');permission['timeframe']=60
        s=base('mtf','mtf',[swing,permission,b('candle','local',direction='up'),b('and','entry',inputs=['permission','local'])],'entry')
        cutoff=START+timedelta(days=1,hours=1)
        e=Evaluator(s,{tf:aggregate(rows,tf) for tf in TIMEFRAMES})
        for row in rows:
            if row.end<cutoff:e.step(row.end)
        self.assertFalse(e.values['entry']['value'])
        e.step(cutoff);self.assertTrue(e.values['entry']['value'])
        low=next(x for x in reversed(e.values['macro']['meta']['pivots']) if x['kind']=='low')
        self.assertEqual(low['confirmed_at'],cutoff.isoformat())
        self.assertLess(low['candidate_time'],low['confirmed_at'])
        changed=[x if x.start<cutoff else Bar(x.start,500,1000,1,500) for x in rows]
        future=Evaluator(s,{tf:aggregate(changed,tf) for tf in TIMEFRAMES})
        for row in changed:
            if row.end<=cutoff:future.step(row.end)
        self.assertEqual(e.values,future.values)

    def test_review_and_saved_strategy_support_60_minutes(self):
        with tempfile.TemporaryDirectory() as d,TestClient(create_app(Path(d)/'hour.db')) as client:
            rows=minutes(120);text='datetime,open,high,low,close\n'+'\n'.join(f'{x.start.isoformat()},{x.open},{x.high},{x.low},{x.close}' for x in rows)
            ds=client.post('/api/import',json={'name':'hour.csv','csv':text}).json()
            s=base('hour-api','hour-api',[b('time_filter','entry',start='08:50',end='09:00')],'entry')
            hour=b('candle','macro');hour['timeframe']=60;s['blocks'].append(hour)
            response=client.post('/api/run',json={'dataset_id':ds['id'],'strategy':s})
            self.assertEqual(response.status_code,200,response.text);id=response.json()['id']
            self.assertEqual(client.get('/api/health').json()['engine'],ENGINE_VERSION)
            for minute,count in [(59,0),(60,1)]:
                replay=client.get(f'/api/runs/{id}/review',params={'timeframe':60,'at':(START+timedelta(minutes=minute)).isoformat()})
                self.assertEqual(replay.status_code,200,replay.text)
                self.assertEqual(len(replay.json()['bars']),count)


if __name__=='__main__':unittest.main()
