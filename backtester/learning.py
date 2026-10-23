"""Small, explainable recipes and chronological, training-only comparisons."""
import copy
import hashlib
import math
from datetime import date

from .catalog import make_block
from .data import day_session
from .engine import canonical, run
from .examples import base
from .schema import validate

VERSION = '1.0'
RECIPES = [
    {'id':'opening','name':'開盤突破','tag':'先從這裡開始','description':'先觀察開盤區間，等收盤站上高點或跌破低點，再跟隨方向。','lesson':'學習等待價格離開區間，並觀察假突破造成的停損。'},
    {'id':'retest','name':'突破後回踩','tag':'願意多等一下','description':'突破開盤區間後，等價格回到邊界，再由同方向 K 棒確認。','lesson':'比較直接追突破與等待回踩的交易次數、進場位置。'},
    {'id':'false_break','name':'假突破反轉','tag':'觀察突破失敗','description':'價格一度越過開盤區間，卻很快收回，等反向 K 棒確認。','lesson':'觀察區間行情；持續單邊走勢可能連續停損。'},
    {'id':'pullback','name':'趨勢回調','tag':'順著結構等待','description':'先確認高低點逐步抬高或降低，等回調後再突破才進場。','lesson':'學習趨勢結構與確認延遲；盤整時可能沒有訊號。'},
]
RECIPE_DETAILS={
    'opening':['等開盤區間完整形成，才開始判斷。','收盤超過區間高點／低點，確認 1 根；不要求額外突破點數。'],
    'retest':['先鎖定突破時的區間邊界，最多等待 10 根目前週期 K 棒。','回踩容差 2 點，第一次回踩後以同方向紅／黑 K 確認。','反向超越鎖定邊界 10 點或等候逾期，取消這次等待。'],
    'false_break':['先越過開盤區間至少 2 點，再於 5 根目前週期 K 棒內收回。','要求反向 K 棒確認；上緣突破失敗做空，下緣跌破失敗做多。'],
    'pullback':['波段左右各比較 2 根，右側 2 根完成後才確認，不回填過去訊號。','要求 HH/HL 或 LH/LL 趨勢；推進至少 10 點，回調深度 20%–80%、最多 20 根。','回調後第二次突破已確認高低點，再以收盤確認進場。'],
}
for _recipe in RECIPES:_recipe['details']=RECIPE_DETAILS[_recipe['id']]
DEFAULTS = {'recipe':'opening','instrument':'MTX','direction':'both','timeframe':1,'opening_minutes':5,
            'stop_points':30,'exit':'rr','reward_r':2,'session':'morning','max_trades':3,'drawdown_budget':20000}


def configuration(value):
    if not isinstance(value,dict):raise ValueError('策略設定須為物件')
    allowed=set(DEFAULTS)|{'costs'}
    if set(value)-allowed:raise ValueError('含有不支援的簡易設定')
    c={**DEFAULTS,**copy.deepcopy(value)}
    choices={'recipe':[r['id'] for r in RECIPES],'instrument':['TX','MTX','TMF'],'direction':['long','short','both'],
             'timeframe':[1,5,15,30],'opening_minutes':[5,10,15,30],'exit':['rr','ma','trailing'],'session':['morning','day']}
    for key,options in choices.items():
        if c[key] not in options or (key in ('timeframe','opening_minutes') and type(c[key]) is not int):raise ValueError('設定選項不合法：'+key)
    for key,low,high in [('stop_points',1,2000),('reward_r',.5,5),('max_trades',1,20),('drawdown_budget',1,100000000)]:
        v=c[key]
        if type(v) not in (int,float) or not math.isfinite(v) or not low<=v<=high or (key=='max_trades' and type(v) is not int):raise ValueError('設定數值超出範圍：'+key)
    costs=base('unused','unused',[],None)['costs'];costs['point_value']={'TX':200,'MTX':50,'TMF':10}[c['instrument']]
    supplied=c.get('costs',{})
    if not isinstance(supplied,dict) or set(supplied)-set(costs):raise ValueError('成本設定不合法')
    c['costs']={**costs,**supplied}
    return c


def recipe(c):return next(r for r in RECIPES if r['id']==c['recipe'])


def strategy_for(config):
    c=configuration(config);b=make_block;kind=c['recipe'];blocks=[]
    if kind=='pullback':
        blocks=[b('swing','reference',left=2,right=2),
                b('n_pattern','long-pattern',source='reference',direction='up',min_push=10),
                b('n_pattern','short-pattern',source='reference',direction='down',min_push=10),
                b('trend_filter','long-trend',source='reference',direction='up'),
                b('trend_filter','short-trend',source='reference',direction='down'),
                b('and','long',inputs=['long-pattern','long-trend']),b('and','short',inputs=['short-pattern','short-trend'])]
    else:
        blocks=[b('opening_range','reference',minutes=c['opening_minutes'])]
        for side,direction,field in [('long','up','high'),('short','down','low')]:
            if kind=='opening':blocks.append(b('breakout',side,source='reference',direction=direction,field=field,mode='close'))
            elif kind=='retest':blocks.append(b('retest',side,source='reference',direction=direction,field=field,within=10,tolerance=2,confirm='color'))
            else:blocks.append(b('false_break',side,source='reference',direction='down' if side=='long' else 'up',field='low' if side=='long' else 'high',within=5,min_break=2,reverse_candle=True))
    blocks.append(b('stop_fixed','stop',points=c['stop_points']))
    stops=['stop'];targets=[];exits={'long':[],'short':[]}
    if c['exit']=='rr':blocks.append(b('target_rr','target',ratio=c['reward_r']));targets=['target']
    elif c['exit']=='ma':blocks.append(b('exit_ma','exit',period=20));exits={'long':['exit'],'short':['exit']}
    else:blocks.append(b('stop_trailing_points','trail',activate=c['stop_points'],distance=c['stop_points']));stops.append('trail')
    for block in blocks:block['timeframe']=1 if block['type']=='opening_range' else c['timeframe']
    s=base('learn-'+hashlib.sha256(canonical([VERSION,c]).encode()).hexdigest()[:20],recipe(c)['name'],blocks,
           'long' if c['direction']!='short' else None,'short' if c['direction']!='long' else None,stops,targets,exits)
    s.update(instrument=c['instrument'],direction=c['direction'],timeframe=c['timeframe'],costs=c['costs'])
    s['limits'].update(entry_end='10:30' if c['session']=='morning' else '13:15',force_close='13:40',max_trades_per_day=c['max_trades'])
    validate(s)
    return s


def rules_for(config):
    c=configuration(config)
    entry=recipe(c)['description']
    if c['recipe']!='pullback':entry=f'以 08:45 起的前 {c["opening_minutes"]} 分鐘建立高低區間。'+entry
    exit={'rr':f'停利設為初始停損距離的 {c["reward_r"]:g} 倍（{c["stop_points"]*c["reward_r"]:g} 點）。',
          'ma':'收盤反向跨越 MA20 後，下一根開盤出場。',
          'trailing':f'獲利達 {c["stop_points"]:g} 點後啟動追蹤，從有利極值回撤 {c["stop_points"]:g} 點出場。'}[c['exit']]
    return [entry,f'{c["timeframe"]} 分 K 收盤確認，下一根可用 1 分 K 開盤成交；只做'+{'long':'多單','short':'空單','both':'多空雙向（同時僅一筆持倉）'}[c['direction']]+'。',
            f'每筆 1 口，固定停損 {c["stop_points"]:g} 點。'+exit,
            f'08:50–'+('10:30' if c['session']=='morning' else '13:15')+f' 允許新單，每日最多 {c["max_trades"]} 筆；13:40 前或日終平倉，不跨日。']


def split_period(bars,settings):
    if not isinstance(settings,dict) or set(settings)-{'start','end'}:raise ValueError('日期設定只接受開始與結束日期')
    first=date.fromisoformat(settings['start']) if settings.get('start') else date.min
    last=date.fromisoformat(settings['end']) if settings.get('end') else date.max
    if first>last:raise ValueError('開始日期不可晚於結束日期')
    days=sorted({b.start.date() for b in bars if day_session(b.start) and first<=b.start.date()<=last})
    if not days:raise ValueError('所選日期沒有日盤資料，請確認 CSV 與日期範圍')
    count=max(1,int(len(days)*.7));train=days[:count];test=days[count:]
    return {'training':{'start':train[0].isoformat(),'end':train[-1].isoformat()},
            'validation':{'start':test[0].isoformat(),'end':test[-1].isoformat()} if test else None,
            'training_days':len(train),'validation_days':len(test),'total_days':len(days)}


def assessment(result,days,budget):
    m=result['metrics'];notes=[]
    enough=m['trade_count']>=30 and days>=20
    if not enough:notes.append('目前少於 30 筆交易或 20 個交易日，樣本偏少；這是學習檢查門檻，不是統計保證。')
    if m['max_drawdown']>budget:notes.append('最大回撤超過你設定的可接受金額。')
    if m['net_pnl']<=0:notes.append('扣除成本後沒有正報酬，先檢討交易與成本，不急著增加條件。')
    if not m['trade_count']:
        root_ids={x for x in result['strategy']['entries'].values() if x}
        signals=sum(s['block_id'] in root_ids for s in result['signals'])
        notes.append('有確認訊號，但沒有完成進場；查看取消原因及進場時段。' if signals else '這段資料沒有符合進場條件；可先擴大日期，確認行情中是否出現所選型態。')
    return {'label':'超過回撤範圍' if m['max_drawdown']>budget else '樣本偏少' if not enough else '需檢討' if m['net_pnl']<=0 else '可繼續驗證',
            'enough_sample':enough,'within_budget':m['max_drawdown']<=budget,'notes':notes,
            'cancellations':result['warnings'][:5]}


def save_result(store,dataset_id,bars,strategy,settings,report):
    result=run(bars,strategy,settings);result['data_report']=report
    store.save_strategy(strategy)
    return result,store.save_run(dataset_id,result)


def compact_metrics(result):return {k:v for k,v in result['metrics'].items() if k!='cumulative_pnl'}


def create_study(store,dataset_id,config,settings=None,compare=False):
    if type(compare) is not bool:raise ValueError('比較設定須為開關')
    c=configuration(config);bars,report=store.dataset(dataset_id);split=split_period(bars,settings or {})
    fingerprint=hashlib.sha256(canonical([VERSION,dataset_id,c,split,compare]).encode()).hexdigest()
    cached=store.learning_study(fingerprint,required=False)
    if cached:return cached
    stops=[c['stop_points']]
    if compare:
        choices=[max(1,round(c['stop_points']*.75)),min(2000,round(c['stop_points']*1.25)),c['stop_points']-1,c['stop_points']+1,c['stop_points']-2,c['stop_points']+2]
        for stop in choices:
            if 1<=stop<=2000 and stop not in stops:stops.append(stop)
            if len(stops)==3:break
    candidates=[]
    for stop in dict.fromkeys(stops):
        variant={**c,'stop_points':stop};strategy=strategy_for(variant)
        result,id=save_result(store,dataset_id,bars,strategy,split['training'],report)
        candidates.append({'id':strategy['strategy_id'],'name':'原始設定' if stop==c['stop_points'] else f'停損 {stop:g} 點',
                           'config':variant,'strategy':strategy,'run_id':id,'metrics':compact_metrics(result),
                           'assessment':assessment(result,split['training_days'],c['drawdown_budget'])})
    doc={'id':fingerprint,'version':VERSION,'dataset_id':dataset_id,'data_name':store.dataset_name(dataset_id),'recipe':recipe(c),'config':c,'split':split,
         'rules':rules_for(c),'candidates':candidates,'data_warnings':report['warnings'],
         'selection_note':'這裡只使用學習期；保留期尚未在這次比較中運算。停損比較維持同一出場規則，R 倍數停利距離會隨停損同步改變。'}
    store.save_learning_study(doc)
    return doc


def validate_candidate(store,study_id,candidate_id):
    study=store.learning_study(study_id)
    candidate=next((c for c in study['candidates'] if c['id']==candidate_id),None)
    if candidate is None:raise ValueError('請選擇這次研究中已完成學習期回測的設定')
    period=study['split']['validation']
    if not period:raise ValueError('只有一個交易日，無法切出獨立保留期；請增加資料天數')
    cached=store.learning_check(study_id,candidate_id)
    if cached:return cached
    previous=store.learning_exposures(study['dataset_id'],period)
    bars,report=store.dataset(study['dataset_id']);strategy=candidate['strategy']
    result,id=save_result(store,study['dataset_id'],bars,strategy,period,report)
    stressed=copy.deepcopy(candidate['config']);slippage=stressed['costs']['slippage'];stressed['costs']['slippage']=slippage*2 if slippage>0 else 1
    stressed_strategy=strategy_for(stressed);stressed_strategy['name']+='・滑價壓力測試'
    stressed_strategy['strategy_id']+='-stress'
    # Zero slippage becomes one point; positive slippage is doubled, with new identity.
    stress,stress_id=save_result(store,study['dataset_id'],bars,stressed_strategy,period,report)
    doc={'study_id':study_id,'candidate_id':candidate_id,'dataset_id':study['dataset_id'],'period':period,
         'run_id':id,'metrics':compact_metrics(result),'assessment':assessment(result,study['split']['validation_days'],study['config']['drawdown_budget']),
         'stress':{'run_id':stress_id,'metrics':compact_metrics(stress),'slippage':stressed['costs']['slippage']},
         'previous_views':previous,'note':'保留期已被查看。之後若依此結果調參，請把它視為已使用的資料，再找另一段未查看行情驗證。'}
    store.save_learning_check(doc)
    return doc
