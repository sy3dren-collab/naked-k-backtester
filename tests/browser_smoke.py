"""End-to-end FastAPI editor, eight real backtests, library and candle replay."""
import csv,json,os,sys,tempfile,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from backtester.server import create_server
from test_extended import fixture

def main():
 from playwright.sync_api import sync_playwright
 with tempfile.TemporaryDirectory() as directory:
  server=create_server(port=0,db_path=Path(directory)/'browser.db');worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
  try:
   with sync_playwright() as p:
    options={'headless':True}
    if os.environ.get('CHROMIUM_PATH'):options['executable_path']=os.environ['CHROMIUM_PATH']
    browser=p.chromium.launch(**options);page=browser.new_page(accept_downloads=True,viewport={'width':1500,'height':1100})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}')
    page.locator('#tool-list [data-kind="pinbar"]').wait_for()
    page.locator('#blocks .graph-block').nth(3).wait_for()
    assert page.locator('#tool-list [data-kind]').count()>=65
    initial=page.locator('#blocks .graph-block').count()
    page.locator('#tool-list [data-kind="pinbar"]').drag_to(page.locator('#blocks'))
    assert page.locator('#blocks .graph-block').count()==initial+1
    page.locator('#inspector [data-param="min_range"]').fill('20')
    page.locator('#inspector [data-param="min_range"]').dispatch_event('change')
    page.locator('#validate-strategy').click();page.wait_for_function("()=>document.getElementById('message').textContent.includes('檢查通過')")
    page.locator('#save-strategy').click();page.wait_for_function("()=>document.getElementById('message').textContent.includes('已儲存策略')")
    page.locator('#inspector [data-param="min_range"]').fill('21');page.locator('#inspector [data-param="min_range"]').dispatch_event('change')
    page.locator('#save-strategy').click();page.wait_for_function("()=>document.getElementById('strategy-version').value==='1.1'")
    page.locator('#clone-strategy').click();page.wait_for_function("()=>document.getElementById('strategy-id').value.includes('-copy-')")
    page.locator('#delete-strategy').click();page.wait_for_function("()=>document.getElementById('message').textContent.includes('已從策略庫刪除')")
    for i in range(8):
     page.locator('[data-tab="workspace"]').click();page.locator('#template').select_option(str(i))
     if i==0:page.locator('#quantity').fill('3')
     data=fixture(i);text='日期,時間,開盤價,最高價,最低價,收盤價,成交量\r\n'+'\r\n'.join(f'{b.start.date().isoformat()},{b.start.strftime("%H:%M:%S")},{b.open},{b.high},{b.low},{b.close},100' for b in data)
     if i==0:
      lines=text.split('\r\n');text=lines[0]+',開盤價,,\r\n'+'\r\n'.join(line+',999,,' for line in lines[1:])
     page.locator('#csv-file').set_input_files({'name':f'人工驗收-{i}.csv','mimeType':'text/csv','buffer':text.encode('cp950')})
     page.wait_for_function("()=>!document.getElementById('import').disabled")
     if i==0:
      assert page.locator('[data-map="open"]').input_value()==''
      assert '重複或空白欄名' in page.locator('#csv-status').text_content()
      page.locator('[data-map="open"]').select_option('開盤價 [第 8 欄]')
      page.locator('#import').click();page.wait_for_function("()=>document.getElementById('message').textContent.includes('OHLC')")
      page.locator('[data-map="open"]').select_option('開盤價 [第 3 欄]')
     page.locator('#run').click();page.locator('#report.active #trades tr').first.wait_for()
     assert page.locator('#metrics .metric').count()==21
     with page.expect_download() as pending:page.locator('#export-result').click()
     result=json.loads(Path(pending.value.path()).read_text());assert result['metrics']['trade_count']==1,(i,result['warnings'])
     if i==0:
      assert '3 口' in page.locator('#trades tr').first.text_content()
      page.locator('#curve-mode').select_option('pnl');assert '累積淨損益' in page.locator('#curve-range').text_content()
      page.locator('#curve-mode').select_option('equity')
      with page.expect_download() as pending:page.locator('#export-trades').click()
      with Path(pending.value.path()).open(encoding='utf-8-sig',newline='') as source:rows=list(csv.DictReader(source))
      assert len(rows)==1 and float(rows[0]['entry_commission'])==result['trades'][0]['entry_fee']['commission']
      assert float(rows[0]['exit_tax'])==result['trades'][0]['exit_fee']['tax']
     page.locator('#trades tr').first.click();page.wait_for_function("()=>document.getElementById('review-info').textContent.includes('已完成')")
     assert page.locator('#review.active').count()==1
     page.wait_for_function("()=>JSON.stringify(Array.from(document.getElementById('candles').getContext('2d').getImageData(5,5,1,1).data))==='[16,19,24,255]'")
     assert '淨損益' in page.locator('#review-trade').text_content()
    page.locator('#review-play').click();page.wait_for_function("()=>document.getElementById('review-play').textContent.includes('暫停')")
    page.locator('#review-play').click()
    page.locator('[data-tab="history"]').click();page.locator('#history-rows button').nth(7).wait_for()
    page.locator('#history-rows button').first.click();page.locator('#report.active').wait_for()
    page.locator('[data-tab="workspace"]').click();page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert not errors,errors
    browser.close();print('PASS: drag toolbox, validation, automatic versions, clone/delete, 8 real CSV strategies, JSON export, candle jump/replay, history, mobile layout')
  finally:server.shutdown();server.server_close();worker.join()
if __name__=='__main__':main()
