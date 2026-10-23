import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from backtester.api import create_app
from backtester.blocks import Evaluator
from backtester.catalog import CATALOG, make_block
from backtester.data import Bar, TAIPEI, aggregate, parse_csv, TIMEFRAMES
from backtester.engine import run
from backtester.examples import templates, base
from backtester.schema import validate

START=datetime(2024,2,1,8,45,tzinfo=TAIPEI)


def candles(values):
    return [Bar(START+timedelta(minutes=i),*row) for i,row in enumerate(values)]


def points(prices): return [(p,p+.5,p-.5,p) for p in prices]


def fixture(index):
    flat=[(100,101,99,100)]
    if index==0:return candles(flat*5+[(100,106,99,105),(106,108,104,107),(107,109,105,108)])
    if index==1:return candles(flat*20+[(100,106,99,105),(105,106,95,96),(95,96,93,94),(94,95,93,94)])
    if index==2:return candles(points([100,99,95,98,100,110,108,105,101,104,108,120,118,112,108,110,114,122,123]))
    if index==3:return candles([(100,101,99,100),(100,101,98,100),(95,96,90,95),(96,99,94,98),(98,101,97,100),(92,96,89,95),(95,99,94,98),(98,101,97,100)])
    if index==4:return candles(flat*20+[(100,106,99,105),(105,106,104,105),(105,106,101,103),(103,105,102,104),(104,105,103,104)])
    if index==5:return candles(flat*5+[(100,106,98,99),(99,100,95,96),(96,98,95,97)])
    if index==6:return candles(flat*12+[(100,106,99,105),(106,108,105,107),(107,109,106,107)])
    return candles(points([100,101,95,100,105,115,112,110,105,110,117,120,118,115,112,116,122,123,110]))


def configured(index):
    s=copy.deepcopy(templates()[index]);s['costs'].update(point_value=10,commission=1,tax_mode='fixed',tax_fixed=.5,slippage=1)
    return s


class AcceptanceTests(unittest.TestCase):
    def test_eight_manual_strategies(self):
        expected=[(6,107,107,-3),(21,106,94,-123),(18,124,122,-23),(7,99,99,-3),
                  (24,105,103,-23),(6,98,98,-3),(13,107,106,-13),(11,121,109,-123)]
        for i,(minute,entry,exit,net) in enumerate(expected):
            with self.subTest(strategy=templates()[i]['name']):
                result=run(fixture(i),configured(i))
                self.assertEqual(len(result['trades']),1)
                trade=result['trades'][0]
                self.assertEqual(trade['entry_time'],(START+timedelta(minutes=minute)).isoformat())
                self.assertEqual(trade['entry_price'],entry)
                self.assertEqual(trade['exit_price'],exit)
                self.assertAlmostEqual(trade['cost'],3)
                self.assertAlmostEqual(trade['net_pnl'],net)
                self.assertTrue(trade['entry_block_id'])
                self.assertTrue(trade['exit_block_id'])

    def test_trailing_stop_only_moves_forward_after_confirmation(self):
        result=run(fixture(7),configured(7))
        updates=result['protection_updates']
        self.assertEqual(updates[0]['stop'],103.5)
        self.assertTrue(any(u['stop']==110.5 and u['time']=='2024-02-01T09:02:00+08:00' for u in updates))
        self.assertTrue(all(b['stop']>=a['stop'] for a,b in zip(updates,updates[1:])))
        self.assertEqual(result['trades'][0]['exit_time'],'2024-02-01T09:03:00+08:00')

    def test_quantity_and_direction(self):
        s=configured(0);s['quantity']=3
        r=run(fixture(0),s)
        self.assertEqual(r['trades'][0]['quantity'],3)
        self.assertEqual(r['trades'][0]['cost'],9)
        self.assertEqual(r['metrics']['net_pnl'],-9)
        s['direction']='short';self.assertEqual(run(fixture(0),s)['trades'],[])

    def test_no_future_signal_or_overlay_backfill_for_eight_strategies(self):
        for i in range(8):
            rows=fixture(i);future=rows+ [Bar(rows[-1].end+timedelta(minutes=n),500,1000,1,500) for n in range(5)]
            a,b=run(rows,configured(i)),run(future,configured(i));cutoff=rows[-1].end.isoformat()
            self.assertEqual(a['signals'],[s for s in b['signals'] if s['trigger_time']<=cutoff])
            self.assertEqual(a['overlays'],[o for o in b['overlays'] if o['time']<=cutoff])


class ExtendedRulesTests(unittest.TestCase):
    def test_30_minute_complete_bars_and_contract_boundaries(self):
        rows=candles([(100,101,99,100)]*31)
        self.assertEqual(len(aggregate(rows,30)),1)
        self.assertEqual(aggregate(rows,30)[0].end,START+timedelta(minutes=30))
        mixed=[Bar(b.start,b.open,b.high,b.low,b.close,contract='202402' if i<15 else '202403') for i,b in enumerate(rows)]
        self.assertEqual(aggregate(mixed,30),[])

    def test_all_catalog_market_blocks_can_evaluate(self):
        market=[make_block('swing','reference'),make_block('box','box-reference'),make_block('candle','bull')]
        for kind,definition in CATALOG.items():
            if definition['category'] in ('stop','target'):continue
            params={}
            for key,spec in definition['params'].items():
                if spec['type']=='price_ref':params[key]='box-reference' if spec.get('accepts')==['box'] else 'reference'
                elif spec['type']=='condition_ref':params[key]='bull'
                elif spec['type']=='condition_refs':params[key]=['bull','bull']
            market.append(make_block(kind,'test-'+kind,**params))
        s=base('catalog','catalog',market,None)
        rows=fixture(2)+[Bar(START+timedelta(minutes=19+i),120,125,115,121) for i in range(40)]
        evaluator=Evaluator(s,{tf:aggregate(rows,tf) for tf in TIMEFRAMES})
        position={'entry_time':START,'entry_price':100,'side':'long','direction':1,'best_points':25}
        for row in rows:evaluator.step(row.end,{'position':position})
        self.assertEqual(len(evaluator.values),len(market))

    def test_not_sequence_abc_delay_count_expire(self):
        b=make_block
        blocks=[b('candle','a',direction='up'),b('candle','b',direction='down'),b('not','c',source='a'),
                b('sequence','seq',inputs=['a','b','a'],within=10,restart_on_a=False),
                b('delay','delay',source='a',bars=2),b('count','count',source='a',window=3,count=2),b('expire','expire',source='a',bars=2)]
        s=base('logic','logic',blocks,None);rows=candles([(100,102,99,101),(101,102,99,100),(100,102,99,101),(100,101,99,100)])
        e=Evaluator(s,{tf:aggregate(rows,tf) for tf in TIMEFRAMES})
        e.step(rows[0].end);self.assertFalse(e.values['seq']['value'])
        e.step(rows[1].end);self.assertTrue(e.values['c']['value'])
        e.step(rows[2].end);self.assertTrue(e.values['seq']['value']);self.assertTrue(e.values['delay']['value']);self.assertTrue(e.values['count']['value'])

    def test_daily_loss_gate_and_stop_first(self):
        s=configured(0);s['risk']={'stop_points':2,'target_points':2};s['limits']['daily_max_loss']=1
        rows=fixture(0)+candles([])
        rows=rows[:6]+[Bar(START+timedelta(minutes=6),105,110,100,106),Bar(START+timedelta(minutes=7),100,106,99,105),Bar(START+timedelta(minutes=8),106,110,100,107)]
        r=run(rows,s);self.assertEqual(len(r['trades']),1);self.assertTrue(r['trades'][0]['ambiguous_order'])


class ExtendedAPITests(unittest.TestCase):
    def test_fastapi_library_and_causal_replay(self):
        with tempfile.TemporaryDirectory() as directory,TestClient(create_app(Path(directory)/'api.db')) as client:
            self.assertEqual(client.get('/api/health').json()['service'],'FastAPI')
            self.assertEqual(len(client.get('/api/templates').json()),8)
            rows=fixture(7)
            csv='datetime,open,high,low,close\n'+'\n'.join(f'{b.start.isoformat()},{b.open},{b.high},{b.low},{b.close}' for b in rows)
            ds=client.post('/api/import',json={'name':'人工驗收.csv','csv':csv}).json()
            response=client.post('/api/run',json={'dataset_id':ds['id'],'strategy':configured(7),'settings':{}})
            self.assertEqual(response.status_code,200,response.text)
            r=response.json();at=(START+timedelta(minutes=12)).isoformat()
            replay=client.get('/api/runs/'+r['id']+'/review',params={'at':at}).json()
            self.assertTrue(all(datetime.fromisoformat(b['start'])+timedelta(minutes=b['minutes'])<=datetime.fromisoformat(at) for b in replay['bars']))
            self.assertTrue(all(o['time']<=at for o in replay['levels']))
            self.assertTrue(replay['trades'])
            self.assertNotIn('exit_time',replay['trades'][0])
            self.assertNotIn('raw_exit_price',replay['trades'][0])
            self.assertNotIn('best_price',replay['trades'][0])
            self.assertEqual(replay['trades'][0]['stop'],103.5)
            cloned=client.post('/api/strategies/clone',json={'strategy':configured(7),'strategy_id':'copy'}).json()
            self.assertEqual(cloned['strategy_id'],'copy')
            self.assertEqual(client.delete('/api/strategies/copy/1.0').status_code,200)
            self.assertFalse(any(s['strategy_id']=='copy' for s in client.get('/api/strategies').json()))
            self.assertEqual(client.get('/api/runs/'+r['id']).status_code,200)

    def test_replay_hides_intraminute_exit_until_that_minute_completes(self):
        with tempfile.TemporaryDirectory() as directory,TestClient(create_app(Path(directory)/'api.db')) as client:
            rows=fixture(0)
            csv='datetime,open,high,low,close\n'+'\n'.join(f'{b.start.isoformat()},{b.open},{b.high},{b.low},{b.close}' for b in rows)
            ds=client.post('/api/import',json={'name':'人工停損.csv','csv':csv}).json()
            s=configured(0);s['risk']={'stop_points':2,'target_points':2}
            result=client.post('/api/run',json={'dataset_id':ds['id'],'strategy':s,'settings':{}}).json()
            trade=result['trades'][0]
            self.assertEqual(trade['exit_time_precision'],'within_1m_bar')
            replay=client.get('/api/runs/'+result['id']+'/review',params={'at':trade['entry_time']}).json()
            self.assertEqual(len(replay['trades']),1)
            for key in ('exit_time','raw_exit_price','exit_price','exit_time_precision','net_pnl','exit_fee','best_points'):
                self.assertNotIn(key,replay['trades'][0])
            completed=(datetime.fromisoformat(trade['exit_time'])+timedelta(minutes=1)).isoformat()
            replay=client.get('/api/runs/'+result['id']+'/review',params={'at':completed}).json()
            self.assertEqual(replay['trades'][0]['net_pnl'],trade['net_pnl'])


if __name__=='__main__':unittest.main()
