"""FastAPI local application, strategy library and causal chart/replay queries."""
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from functools import lru_cache

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from .catalog import catalog
from .data import aggregate, TIMEFRAMES
from .engine import run
from .runner import ENGINE_VERSION
from .examples import templates
from .store import Store
from .strategy import validate
from .learning import RECIPES, DEFAULTS, configuration, strategy_for, rules_for, create_study, validate_candidate

STATIC = Path(__file__).resolve().parents[1]/'static'


def create_app(db_path=None):
    store = Store(db_path or STATIC.parent/'data'/'backtester.sqlite3')
    app = FastAPI(title='裸 K Lab', version=ENGINE_VERSION)
    app.state.store = store

    @app.middleware('http')
    async def local_requests(request: Request, call_next):
        if request.method in ('POST', 'DELETE', 'PUT', 'PATCH'):
            origin = request.headers.get('origin')
            if origin and urlparse(origin).netloc != request.headers.get('host'):
                return JSONResponse({'error': '拒絕跨來源請求'}, status_code=403)
            if request.method != 'DELETE' and request.headers.get('content-type', '').split(';')[0] != 'application/json':
                return JSONResponse({'error': '請使用 application/json'}, status_code=415)
            try:
                if int(request.headers.get('content-length', '0')) > 256*1024*1024:
                    return JSONResponse({'error': '請求超過 256 MiB，請分批匯入'}, status_code=413)
            except ValueError:
                return JSONResponse({'error': '請求長度不合法'}, status_code=400)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        return response

    async def bad_input(request, error): return JSONResponse({'error': str(error)}, status_code=400)
    for error in (ValueError, KeyError, TypeError, RequestValidationError): app.add_exception_handler(error, bad_input)

    @app.get('/api/health')
    def health(): return {'status': 'ok', 'engine': ENGINE_VERSION, 'service': 'FastAPI'}

    @app.get('/api/templates')
    def get_templates(): return templates()

    @app.get('/api/catalog')
    def get_catalog(): return catalog()

    @app.get('/api/learning/recipes')
    def learning_recipes():return {'recipes':RECIPES,'defaults':DEFAULTS}

    @app.post('/api/learning/preview')
    def learning_preview(body:dict):
        config=configuration(body.get('config',{}))
        return {'config':config,'strategy':strategy_for(config),'rules':rules_for(config)}

    @app.post('/api/learning/run')
    def learning_run(body:dict):
        return study_view(create_study(store,body['dataset_id'],body.get('config',{}),body.get('settings',{}),body.get('compare',False)))

    @app.get('/api/learning/studies')
    def learning_studies():return store.learning_studies()

    @app.get('/api/learning/studies/{id}')
    def learning_study(id:str):return study_view(store.learning_study(id))

    @app.post('/api/learning/check')
    def learning_check(body:dict):
        if set(body)-{'study_id','candidate_id'}:raise ValueError('驗證只接受研究與候選設定，不可臨時修改參數或日期')
        return validate_candidate(store,body['study_id'],body['candidate_id'])

    def study_view(study):
        period=study['split']['validation']
        return {**study,'holdout_views':store.learning_exposures(study['dataset_id'],period) if period else 0,
                'checked_candidates':store.learning_check_ids(study['id'])}

    @app.post('/api/validate')
    def validate_strategy(body: dict): return {'valid': True, 'ordered_ids': [b['id'] for b in validate(body['strategy'])]}

    @app.get('/api/datasets')
    def datasets(): return store.datasets()

    @app.post('/api/import')
    def import_data(body: dict):
        if not isinstance(body.get('csv'), str) or not isinstance(body.get('mapping', {}), dict): raise ValueError('CSV 須為文字，欄位對應須為物件')
        return store.import_data(str(body.get('name', 'import.csv')), body['csv'].encode(), body.get('mapping'))

    @app.get('/api/strategies')
    def strategies(): return store.strategies()

    @app.post('/api/strategies')
    def save_strategy(body: dict): store.save_strategy(body['strategy']); return {'status': 'saved'}

    @app.post('/api/strategies/version')
    def save_new_version(body: dict):
        strategy = store.prepare_version(body['strategy']); store.save_strategy(strategy); return strategy

    @app.post('/api/strategies/clone')
    def clone_strategy(body: dict): return store.clone_strategy(body['strategy'], body['strategy_id'], body.get('name'))

    @app.delete('/api/strategies/{id}/{version}')
    def delete_strategy(id: str, version: str): store.delete_strategy(id, version); return {'status': 'deleted', 'history_preserved': True}

    @app.post('/api/run')
    def backtest(body: dict):
        bars, report = store.dataset(body['dataset_id']); settings = body.get('settings', {})
        if set(settings)-{'start', 'end'}: raise ValueError('回測設定只支援 start/end')
        strategy = store.prepare_version(body['strategy']) if body.get('auto_version') else body['strategy']
        validate(strategy); result = run(bars, strategy, settings); store.save_strategy(strategy)
        result['data_report'] = report
        return {'id': store.save_run(body['dataset_id'], result), **result}

    @app.get('/api/runs')
    def runs(): return store.runs()

    @app.get('/api/runs/{id}')
    def result(id: str): return {'id': id, **store.result(id)}

    @app.get('/api/runs/{id}/review')
    def review(id: str, timeframe: int = 1, at: str | None = None, offset: int = 0, limit: int = 300):
        if timeframe not in TIMEFRAMES or not 1 <= limit <= 2000 or offset < 0: raise ValueError('圖表週期／分頁參數不合法')
        result, rows = review_series(id, timeframe)
        cursor = datetime.fromisoformat(at) if at else rows[-1].end if rows else None
        if cursor and cursor.tzinfo is None: raise ValueError('播放游標須包含台灣時區')
        completed = [b for b in rows if cursor is None or b.end <= cursor]
        selected = completed[max(0, len(completed)-offset-limit):max(0, len(completed)-offset)]
        levels = {}
        for overlay in result.get('overlays', []):
            if cursor is None or datetime.fromisoformat(overlay['time']) <= cursor: levels[overlay['block_id']] = overlay
        trades = []
        protection = [u for u in result.get('protection_updates', []) if cursor is None or datetime.fromisoformat(u['time']) <= cursor]
        for trade in result['trades']:
            from datetime import timedelta
            entered_at = datetime.fromisoformat(trade['entry_time'])+(timedelta(minutes=1) if trade.get('entry_intrabar_uncertain') else timedelta())
            exited_at = datetime.fromisoformat(trade['exit_time'])+(timedelta(minutes=1) if trade.get('exit_time_precision') == 'within_1m_bar' else timedelta())
            if cursor is None or entered_at <= cursor:
                item = dict(trade)
                if cursor and exited_at > cursor:
                    for key in ('exit_time', 'exit_price', 'raw_exit_price', 'exit_time_precision', 'exit_reason', 'exit_block_id', 'exit_fee', 'net_pnl', 'gross_pnl', 'cost', 'equity_after', 'realized_r', 'best_price', 'best_points', 'structure_peak', 'stop', 'stop_block_id', 'ambiguous_order'): item.pop(key, None)
                    known = next((u for u in reversed(protection) if u['position_id'] == trade.get('position_id')), None)
                    if known: item['stop'] = known['stop']; item['stop_block_id'] = known['stop_block_id']
                trades.append(item)
        visible_start = selected[0].start.isoformat() if selected else ''
        older = {}
        visible_overlays = []
        for overlay in result.get('overlays', []):
            if cursor and datetime.fromisoformat(overlay['time']) > cursor: continue
            if overlay['time'] < visible_start: older[overlay['block_id']] = overlay
            else: visible_overlays.append(overlay)
        return {'bars': [b.json() for b in selected], 'timeframe': timeframe, 'cursor': cursor.isoformat() if cursor else None,
                'total_completed': len(completed), 'total': len(rows), 'levels': list(levels.values()), 'trades': trades,
                'overlay_history': list(older.values())+visible_overlays, 'protection': protection,
                'first_time': rows[0].end.isoformat() if rows else None, 'last_time': rows[-1].end.isoformat() if rows else None,
                'previous_time': completed[-2].end.isoformat() if len(completed)>1 else None,
                'next_time': rows[len(completed)].end.isoformat() if len(completed)<len(rows) else None}

    @lru_cache(maxsize=4)
    def review_series(id, timeframe):
        result, bars = review_run(id)
        start, end = result['settings'].get('start'), result['settings'].get('end')
        rows = [b for b in aggregate(bars, timeframe) if (not start or b.start.date().isoformat() >= start) and (not end or b.start.date().isoformat() <= end)]
        return result, rows

    @lru_cache(maxsize=2)
    def review_run(id):
        result = store.result(id); match = store.run_metadata(id)
        bars, _ = store.dataset(match['dataset_id'])
        return result, bars

    @app.get('/')
    def index(): return FileResponse(STATIC/'shell.html', media_type='text/html')

    @app.get('/{filename}')
    def asset(filename: str):
        if '/' in filename or filename not in {p.name for p in STATIC.iterdir() if p.suffix in ('.js', '.css')}: return JSONResponse({'error': '找不到頁面'}, status_code=404)
        return FileResponse(STATIC/filename)
    return app
