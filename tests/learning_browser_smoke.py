"""Beginner workflow through real CSV, training comparison and locked holdout."""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from backtester.server import create_server
from test_learning import market


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as directory:
        server=create_server(port=0,db_path=Path(directory)/'browser.db');worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            with sync_playwright() as p:
                opts={'headless':True}
                if os.environ.get('CHROMIUM_PATH'):opts['executable_path']=os.environ['CHROMIUM_PATH']
                browser=p.chromium.launch(**opts);page=browser.new_page(accept_downloads=True,viewport={'width':1500,'height':1050})
                errors=[];requests=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.locator('.recipe-card').nth(3).wait_for()
                page.wait_for_function("()=>document.getElementById('learn-rules').textContent.includes('固定停損')")
                assert not page.locator('.strategy-card').is_visible()
                assert not page.locator('#cost-details').evaluate('el=>el.open')
                assert page.locator('[data-cost="point_value"]').input_value()=='50'
                out=Path(os.environ.get('SCREENSHOT_DIR',directory));out.mkdir(exist_ok=True,parents=True)
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(out/'learning-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(out/'learning-mobile.png'),full_page=True)
                page.locator('#quick-run').click();page.wait_for_function("()=>document.getElementById('message').textContent.includes('先選擇左邊')")
                page.set_viewport_size({'width':1500,'height':1050})
                rows=market();text='日期,時間,開盤價,最高價,最低價,收盤價,成交量,備註,備註,,\r\n'+'\r\n'.join(f'{b.start.date()},{b.start:%H:%M:%S},{b.open},{b.high},{b.low},{b.close},100,a,b,,' for b in rows)
                page.locator('#csv-file').set_input_files({'name':'人工學習驗收.csv','mimeType':'text/csv','buffer':text.encode('cp950')})
                page.wait_for_function("()=>!document.getElementById('import').disabled")
                assert not page.locator('#csv-details').evaluate('el=>el.open')
                page.locator('#simple-compare').click();page.locator('#study.active #candidate-cards button').nth(2).wait_for()
                assert '學習期 · 7 個交易日' in page.locator('#study-context').text_content()
                assert '保留期 · 3 個交易日' in page.locator('#study-context').text_content()
                assert not any('/learning/check' in r for r in requests)
                assert not page.locator('#validation-content').is_visible()
                study_id=page.locator('#study-library').input_value();page.locator('#candidate-cards button').nth(1).click()
                page.locator('#check-holdout').click();page.locator('#validation-content:not([hidden]) #view-validation').wait_for()
                assert '樣本偏少' in page.locator('#selected-assessment').text_content()
                assert '這段資料現在已被查看' in page.locator('#message').text_content()
                page.evaluate('scrollTo(0,0)');page.screenshot(path=str(out/'learning-comparison.png'),full_page=True)
                page.locator('#view-training').click();page.locator('#report.active').wait_for()
                assert page.locator('#metrics .metric:visible').count()==6
                page.locator('#report-detail-toggle').click();assert page.locator('#metrics .metric:visible').count()==21
                page.locator('#trades tr').first.click();page.locator('#review.active').wait_for()
                page.wait_for_function("()=>document.getElementById('review-info').textContent.includes('已完成')")
                page.reload();page.locator('.recipe-card').nth(3).wait_for();page.locator('[data-tab="study"]').click()
                page.locator('#study-library').select_option(study_id);page.locator('#candidate-cards button').nth(2).wait_for()
                assert '已有檢視紀錄' in page.locator('#holdout-hint').text_content()
                assert '已查看保留期' in page.locator('#candidate-cards button').nth(1).text_content()
                page.locator('#candidate-cards button').nth(1).click();page.locator('#study-back').click();page.locator('#workspace.active').wait_for()
                assert page.locator('#learn-stop').input_value()=='22'
                page.locator('[data-recipe="retest"]').click();page.locator('#learn-stop').fill('41');page.locator('#learn-stop').dispatch_event('change')
                page.locator('#learn-exit').select_option('ma');page.locator('#simple-to-advanced').click();page.locator('.strategy-card:visible').wait_for()
                assert page.locator('#mode-advanced').get_attribute('aria-pressed')=='true'
                page.locator('#validate-strategy').click();page.wait_for_function("()=>document.getElementById('message').textContent.includes('檢查通過')")
                with page.expect_download() as pending:page.locator('#export-strategy').click()
                strategy=json.loads(Path(pending.value.path()).read_text())
                assert strategy['instrument']=='MTX' and strategy['costs']['point_value']==50
                assert next(b for b in strategy['blocks'] if b['type']=='stop_fixed')['params']['points']==41
                assert strategy['risk']['long']['stop_blocks']==['stop']
                page.locator('#mode-simple').click();page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors,errors
                browser.close();print('PASS: default beginner mode, plain rules, real Big5 CSV with repeated headers, 3 training-only variants, selected holdout, cost stress, saved research, 6-metric report, candle review, advanced handoff and mobile layout')
        finally:server.shutdown();server.server_close();worker.join()


if __name__=='__main__':main()
