"""Real user CSV, Big5, auto-import and browser storage checks for the HTML build."""
import json
import os
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_standalone import build


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as directory:
        target = build(Path(directory))
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=directory))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                launch = {'headless': True}
                if os.environ.get('CHROMIUM_PATH'):
                    launch['executable_path'] = os.environ['CHROMIUM_PATH']
                browser = p.chromium.launch(**launch)
                page = browser.new_page(accept_downloads=True)
                errors, requests = [], []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: requests.append(r.url))
                url = f'http://127.0.0.1:{server.server_port}/{target.name}'
                page.goto(url)
                page.locator('#blocks .block').nth(2).wait_for()
                values = [(17978,17978,17950,17973,3537),(17973,17985,17972,17976,1645),
                          (17976,17988,17973,17980,1161),(17980,17993,17978,17984,1156),
                          (17984,17984,17975,17975,596),(17975,18010,17975,18005,489),
                          (18006,18010,18000,18008,509),(18008,18012,18005,18010,940)]
                text = '日期,時間,開盤價,最高價,最低價,收盤價,成交量\r\n' + '\r\n'.join(
                    f'2024/2/1,08:{45+i:02}:00,' + ','.join(map(str, v)) for i, v in enumerate(values))
                for encoding in ('cp950', 'utf-8-sig', 'utf-16'):
                    page.locator('#csv-file').set_input_files({'name':f'2024~2026小台一分K-{encoding}.csv',
                        'mimeType':'text/csv','buffer':text.encode(encoding)})
                    page.wait_for_function("() => !document.getElementById('import').disabled && document.getElementById('csv-status').textContent.includes('已自動對應')")
                    expected = {'datetime':'日期','time':'時間','open':'開盤價','high':'最高價','low':'最低價','close':'收盤價','volume':'成交量'}
                    for key, value in expected.items():
                        assert page.locator(f'[data-map="{key}"]').input_value() == value
                    assert '�' not in page.locator('#mapping').text_content()
                    assert '17978' in page.locator('#csv-preview').text_content()
                    # Direct Run must perform import first; the user need not click two buttons.
                    page.locator('#run').click()
                    page.locator('#report.active #trades tr').first.wait_for()
                    with page.expect_download() as pending:
                        page.locator('#export-result').click()
                    downloaded = pending.value
                    result = json.loads(Path(downloaded.path()).read_text())
                    assert result['metrics']['trade_count'] == 1
                    assert result['trades'][0]['entry_price'] == 18007
                    assert result['trades'][0]['entry_time'] == '2024-02-01T08:51:00+08:00'
                    assert result['data_report']['errors'] == []
                    assert result['storage_mode'] == 'persistent'
                    assert page.locator('#dataset').input_value()
                    page.locator('[data-tab="workspace"]').click()
                # Browser mode must recalculate edited costs, not return a stored demonstration result.
                page.locator('#strategy-version').fill('1.1')
                page.locator('[data-cost="commission"]').fill('99')
                page.locator('#run').click()
                page.locator('#report.active #trades tr').first.wait_for()
                assert '1.1' in page.locator('#result-label').text_content()
                page.reload()
                page.locator('#blocks .block').nth(2).wait_for()
                page.locator('[data-tab="history"]').click()
                page.locator('#history-rows button').nth(3).wait_for()
                assert 'opening-fixed' in page.locator('#history-rows').text_content()
                assert not any('/api/' in request for request in requests), requests
                assert not errors, errors
                browser.close()
                print('PASS: Big5 / UTF-8 / UTF-16 Chinese split dates, real CSV auto-import, custom-cost calculation, persistence, no backend requests')
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__ == '__main__':
    main()
