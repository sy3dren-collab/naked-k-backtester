"""Regression checks for opening the isolated Index entry and restricted previews."""
import json
import os
import sys
import tempfile
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_standalone import build, RELEASE


def csv_sample():
    values=[(100,101,99,100)]*5+[(100,106,99,105),(106,108,104,107),(107,109,105,108)]
    return '日期,時間,開盤價,最高價,最低價,收盤價,成交量\r\n'+'\r\n'.join(
        f'2024/2/{day},08:{45+i:02}:00,'+','.join(map(str,v))+',100' for day in (1,2) for i,v in enumerate(values))


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as directory:
        target=build(Path(directory))
        archive=target.parent/f'naked-k-backtester-v{RELEASE}.zip'
        with zipfile.ZipFile(archive) as z:
            assert z.namelist()[0]=='index.html'
            assert z.read('index.html')==target.read_bytes()
            assert z.read('naked-k-backtester/index.html')==target.read_bytes()
            for name in z.namelist():
                if name.endswith('index.html'):
                    assert z.read(name)==target.read_bytes(),name
        (target.parent/'frame.html').write_text('<iframe id="preview" sandbox="allow-scripts allow-downloads" src="index.html"></iframe>')
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=directory))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                options={'headless':True}
                if os.environ.get('CHROMIUM_PATH'):options['executable_path']=os.environ['CHROMIUM_PATH']
                browser=p.chromium.launch(**options)
                page=browser.new_page(accept_downloads=True,viewport={'width':390,'height':844})
                errors,requests=[],[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:requests.append(r.url))
                base=f'http://127.0.0.1:{server.server_port}'
                page.goto(base+'/index.html')
                page.locator('#blocks .block').nth(2).wait_for()
                assert page.locator('.sidebar').evaluate('el=>getComputedStyle(el).backgroundColor')=='rgb(19, 46, 40)'
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                strategy=page.evaluate('JSON.parse(JSON.stringify(LOCAL_TEMPLATES[0]))')
                strategy['strategy_id']='imported-numeric-version';strategy['version']=1
                page.locator('#strategy-file').set_input_files({'name':'strategy.json','mimeType':'application/json','buffer':json.dumps(strategy).encode()})
                page.wait_for_function("()=>document.getElementById('strategy-id').value==='imported-numeric-version'")
                page.locator('#csv-file').set_input_files({'name':'range-big5.csv','mimeType':'text/csv','buffer':csv_sample().encode('cp950')})
                page.wait_for_function("()=>!document.getElementById('import').disabled")
                page.locator('#start').fill('2024-02-02');page.locator('#end').fill('2024-02-02')
                page.locator('#run').click();page.locator('#report.active').wait_for()
                with page.expect_download() as pending:page.locator('#export-result').click()
                result=json.loads(Path(pending.value.path()).read_text())
                assert result['settings']=={'start':'2024-02-02','end':'2024-02-02'}
                assert len(result['equity'])==8
                page.locator('[data-tab="workspace"]').click()
                page.locator('#csv-file').set_input_files({'name':'bad.csv','mimeType':'text/csv','buffer':b'\xff\x00\x81'})
                page.wait_for_function("()=>document.getElementById('csv-status').textContent.includes('解碼') && !document.getElementById('csv-status').textContent.includes('正在')")
                assert not page.locator('#mapping').is_visible()
                assert not page.locator('#csv-preview').text_content()
                page.locator('#sample').click()
                page.wait_for_function("()=>document.getElementById('dataset').value.length>0")
                page.locator('#run').click();page.locator('#report.active').wait_for()
                # A preview without same-origin permissions cannot use IndexedDB or a worker;
                # styles and calculations must remain usable in session-only mode.
                page.goto(base+'/frame.html')
                frame=page.frame_locator('#preview')
                frame.locator('#blocks .block').nth(2).wait_for()
                assert frame.locator('.sidebar').evaluate('el=>getComputedStyle(el).backgroundColor')=='rgb(19, 46, 40)'
                frame.locator('#sample').click()
                page.wait_for_timeout(100)
                frame.locator('#run').click();frame.locator('#report.active').wait_for()
                assert '限制持久儲存' in frame.locator('#message').text_content()
                assert not any(url.endswith(('/style.css','/app.js','/csv.js')) or '/api/' in url for url in requests)
                assert not errors,errors
                browser.close()
                print('PASS: isolated Index styles/scripts, mobile width, archive entry, opaque preview fallback, date preservation, imported version, decode-error recovery')
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
