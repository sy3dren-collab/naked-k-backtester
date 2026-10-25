import copy
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from backtester.api import create_app
from backtester.data import Bar, TIMEFRAMES
from backtester.learning import RECIPES, configuration, strategy_for, rules_for, split_period, create_study, validate_candidate
from backtester.schema import validate
from backtester.store import Store
from test_extended import fixture, START


def market(days=10):
    rows=[];day=0;count=0
    while count<days:
        stamp=START+timedelta(days=day);day+=1
        if stamp.weekday()>=5:continue
        rows += [Bar(b.start+timedelta(days=day-1),b.open,b.high,b.low,b.close,100) for b in fixture(0)]
        count+=1
    return rows


def csv(rows):return 'datetime,open,high,low,close,volume\n'+'\n'.join(f'{b.start.isoformat()},{b.open},{b.high},{b.low},{b.close},100' for b in rows)


class RecipeTests(unittest.TestCase):
    def test_all_recipe_exit_timeframe_combinations_have_valid_bound_protection(self):
        for r in RECIPES:
            for exit in ('rr','ma','trailing'):
                for tf in TIMEFRAMES:
                    for side in ('long','short','both'):
                        with self.subTest(recipe=r['id'],exit=exit,tf=tf,side=side):
                            s=strategy_for({'recipe':r['id'],'exit':exit,'timeframe':tf,'direction':side})
                            validate(s);self.assertEqual(s['quantity'],1)
                            for direction in ('long','short'):
                                self.assertIn('stop',s['risk'][direction]['stop_blocks'])
                            self.assertEqual(s['entries']['short'],None if side=='long' else 'short')
                            self.assertEqual(s['entries']['long'],None if side=='short' else 'long')
                            self.assertEqual(len(rules_for({'recipe':r['id'],'exit':exit,'timeframe':tf,'direction':side})),4)

    def test_costs_and_risk_are_not_silently_changed(self):
        c={'instrument':'TMF','stop_points':17,'reward_r':1.5,'costs':{'point_value':12,'commission':99,'slippage':.25}}
        s=strategy_for(c)
        self.assertEqual(s['costs']['point_value'],12)
        self.assertEqual(s['costs']['commission'],99)
        self.assertEqual(s['blocks'][-2]['params']['points'],17)
        self.assertEqual(s['blocks'][-1]['params']['ratio'],1.5)
        self.assertEqual(s['strategy_id'],strategy_for(copy.deepcopy(c))['strategy_id'])

    def test_invalid_parameters_are_rejected(self):
        for c in ({'stop_points':0},{'stop_points':float('nan')},{'timeframe':True},{'max_trades':1.5},{'recipe':'magic'},{'drawdown_budget':-1},{'unknown':3},{'costs':{'commission':-1}}):
            with self.subTest(c=c),self.assertRaises(ValueError):strategy_for(c)

    def test_split_uses_complete_trading_dates_and_respects_date_selection(self):
        rows=market();s=split_period(rows,{})
        self.assertEqual((s['training_days'],s['validation_days']),(7,3))
        self.assertLess(s['training']['end'],s['validation']['start'])
        dates=sorted({b.start.date().isoformat() for b in rows})
        small=split_period(rows,{'start':dates[2],'end':dates[5]})
        self.assertEqual((small['training_days'],small['validation_days']),(2,2))
        self.assertEqual(small['training']['start'],dates[2])
        self.assertEqual(small['validation']['end'],dates[5])
        self.assertIsNone(split_period(market(1),{})['validation'])


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'study.db')
        self.dataset=self.store.import_data('人工學習行情.csv',csv(market()).encode())['id']
    def tearDown(self):self.tmp.cleanup()

    def test_comparison_only_runs_training_and_persists_reproducibly(self):
        study=create_study(self.store,self.dataset,{},compare=True)
        self.assertEqual(len(study['candidates']),3)
        self.assertEqual(study['candidates'][0]['name'],'原始設定')
        self.assertEqual(len(self.store.runs()),3)
        for c in study['candidates']:
            r=self.store.result(c['run_id'])
            self.assertEqual(r['settings'],study['split']['training'])
            self.assertTrue(all(t['exit_time'][:10]<=study['split']['training']['end'] for t in r['trades']))
            self.assertNotIn('cumulative_pnl',c['metrics'])
            self.assertFalse(c['assessment']['enough_sample'])
        self.assertEqual(create_study(self.store,self.dataset,{},compare=True),study)
        self.assertEqual(self.store.learning_study(study['id']),study)

    def test_each_guided_recipe_fills_at_the_manually_confirmed_minute(self):
        for name,index,minute in [('opening',0,6),('retest',4,24),('false_break',5,6),('pullback',2,18)]:
            with self.subTest(recipe=name):
                ds=self.store.import_data(name+'.csv',csv(fixture(index)).encode())['id']
                study=create_study(self.store,ds,{'recipe':name})
                result=self.store.result(study['candidates'][0]['run_id'])
                self.assertEqual(len(result['trades']),1)
                self.assertEqual(result['trades'][0]['entry_time'],(START+timedelta(minutes=minute)).isoformat())

    def test_validation_keeps_selected_strategy_and_tracks_holdout_reuse(self):
        study=create_study(self.store,self.dataset,{},compare=True);c=study['candidates'][0]
        check=validate_candidate(self.store,study['id'],c['id'])
        self.assertEqual(check['previous_views'],0)
        self.assertEqual(len(self.store.runs()),5)
        result=self.store.result(check['run_id'])
        self.assertEqual(result['strategy'],c['strategy'])
        self.assertEqual(result['settings'],study['split']['validation'])
        self.assertTrue(all(t['entry_time'][:10]>=study['split']['validation']['start'] for t in result['trades']))
        stressed=self.store.result(check['stress']['run_id'])
        self.assertEqual(stressed['strategy']['costs']['slippage'],2)
        self.assertNotEqual(stressed['strategy']['strategy_id'],result['strategy']['strategy_id'])
        self.assertEqual(validate_candidate(self.store,study['id'],c['id']),check)
        self.assertEqual(self.store.learning_exposures(self.dataset,check['period']),1)
        second=validate_candidate(self.store,study['id'],study['candidates'][1]['id'])
        self.assertEqual(second['previous_views'],1)
        with self.assertRaises(ValueError):validate_candidate(self.store,study['id'],'another-strategy')

    def test_future_holdout_prices_cannot_change_training_comparison(self):
        rows=market();split=split_period(rows,{})
        altered=[Bar(b.start,b.open+1000,b.high+2000,b.low,b.close+1000,b.volume) if b.start.date().isoformat()>=split['validation']['start'] else b for b in rows]
        second=self.store.import_data('不同保留期.csv',csv(altered).encode())['id']
        a=create_study(self.store,self.dataset,{},compare=True);b=create_study(self.store,second,{},compare=True)
        self.assertEqual([c['metrics'] for c in a['candidates']],[c['metrics'] for c in b['candidates']])

    def test_single_day_still_runs_but_cannot_claim_holdout(self):
        id=self.store.import_data('一天.csv',csv(market(1)).encode())['id'];study=create_study(self.store,id,{})
        self.assertIsNone(study['split']['validation'])
        self.assertEqual(study['candidates'][0]['assessment']['label'],'樣本偏少')
        with self.assertRaisesRegex(ValueError,'只有一個交易日'):validate_candidate(self.store,study['id'],study['candidates'][0]['id'])

    def test_zero_trades_are_explained_and_boundary_comparisons_remain_small(self):
        study=create_study(self.store,self.dataset,{'recipe':'pullback','stop_points':1},compare=True)
        self.assertEqual(len(study['candidates']),3)
        self.assertEqual(study['candidates'][0]['metrics']['trade_count'],0)
        self.assertTrue(any('沒有符合進場條件' in n for n in study['candidates'][0]['assessment']['notes']))
        self.assertEqual(len({c['config']['stop_points'] for c in study['candidates']}),3)

    def test_stress_identity_cannot_collide_with_a_later_normal_cost_setting(self):
        study=create_study(self.store,self.dataset,{})
        check=validate_candidate(self.store,study['id'],study['candidates'][0]['id'])
        later=create_study(self.store,self.dataset,{'costs':{'slippage':2}})
        normal=self.store.result(later['candidates'][0]['run_id'])
        stress=self.store.result(check['stress']['run_id'])
        self.assertNotEqual(normal['strategy']['strategy_id'],stress['strategy']['strategy_id'])

    def test_api_workflow_survives_server_restart(self):
        path=Path(self.tmp.name)/'api.db'
        with TestClient(create_app(path)) as client:
            self.assertEqual(len(client.get('/api/learning/recipes').json()['recipes']),4)
            ds=client.post('/api/import',json={'name':'人工.csv','csv':csv(market())}).json()['id']
            response=client.post('/api/learning/run',json={'dataset_id':ds,'config':{},'compare':True})
            self.assertEqual(response.status_code,200,response.text);study=response.json()
            self.assertEqual(study['holdout_views'],0)
            self.assertEqual(len(client.get('/api/runs').json()),3)
            body={'study_id':study['id'],'candidate_id':study['candidates'][0]['id']}
            self.assertEqual(client.post('/api/learning/check',json={**body,'config':{'stop_points':1}}).status_code,400)
            self.assertEqual(client.post('/api/learning/check',json=body).status_code,200)
        with TestClient(create_app(path)) as client:
            self.assertEqual(client.get('/api/learning/studies').json()[0]['id'],study['id'])
            self.assertEqual(client.get('/api/learning/studies/'+study['id']).json()['holdout_views'],1)
            self.assertEqual(client.post('/api/learning/check',json=body).json()['previous_views'],0)


if __name__=='__main__':unittest.main()
