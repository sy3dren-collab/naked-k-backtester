"""Build a real browser backtester, without a server, CDN, or canned results."""
import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = '1.2'
sys.path.insert(0, str(ROOT))
from backtester.strategy import templates


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    static = ROOT / 'legacy' / 'standalone'
    sources = {name: (static / name).read_text(encoding='utf-8') for name in ('csv.js', 'engine.js', 'local-store.js', 'app.js', 'style.css', 'shell.html')}
    template_json = (static / 'templates.json').read_text(encoding='utf-8')
    bootstrap = '\n'.join(sources[name] for name in ('csv.js', 'engine.js', 'local-store.js'))
    bootstrap += '\nconst localAPI=NakedLocal.createAPI(' + template_json + ",(...args)=>self.postMessage({progress:args}));"
    bootstrap += "\nlet queue=Promise.resolve();self.onmessage=e=>{const {id,path,body}=e.data;queue=queue.then(async()=>{try{self.postMessage({id,value:await localAPI(path,body)});}catch(error){self.postMessage({id,error:error.message});}});};"
    bridge = '''
const LOCAL_TEMPLATES=__TEMPLATES__;
let worker=null,fallback=null,sequence=0;const pending=new Map();
function progressUpdate(args){const [kind,done,total]=args;const element=document.getElementById('csv-status');if(kind==='import')element.textContent='正在檢查行情與儲存資料…';else if(kind==='run')element.textContent=`正在回測 ${done.toLocaleString()} / ${total.toLocaleString()} 根日盤 K…`;}
try{
  const url=URL.createObjectURL(new Blob([__WORKER__],{type:'text/javascript'}));worker=new Worker(url);URL.revokeObjectURL(url);
  worker.onmessage=e=>{if(e.data.progress){progressUpdate(e.data.progress);return;}const item=pending.get(e.data.id);if(!item)return;pending.delete(e.data.id);if(e.data.error)item.reject(Error(e.data.error));else item.resolve(e.data.value);};
  worker.onerror=()=>{worker.terminate();worker=null;fallback=NakedLocal.createAPI(LOCAL_TEMPLATES,progressUpdate);for(const item of pending.values())fallback(item.path,item.body).then(item.resolve,item.reject);pending.clear();};
}catch(_){worker=null;}
if(!worker)fallback=NakedLocal.createAPI(LOCAL_TEMPLATES,progressUpdate);
window.NAKED_LOCAL_API=async(path,body)=>{if(!worker){await new Promise(resolve=>setTimeout(resolve,0));return fallback(path,body);}return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject,path,body});try{worker.postMessage({id,path,body});}catch(error){pending.delete(id);reject(error);}});};
'''.replace('__TEMPLATES__', template_json).replace('__WORKER__', json.dumps(bootstrap, ensure_ascii=False))
    html = sources['shell.html']
    html = html.replace('<title>裸 K Lab · 策略回測工作台</title>', f'<title>裸 K Lab · 獨立網頁回測版 v{RELEASE}</title>')
    # Keep styles inside the document body, including viewers which render body content.
    html = html.replace('<link rel="stylesheet" href="/style.css">', '')
    html = html.replace('<body>', '<body><style>' + sources['style.css'] + '\n.standalone-note{padding:12px 16px;margin:18px 0;background:#e7f1ec;border:1px solid #b3c9ba;border-radius:5px;font-size:12px;color:#285342}</style>')
    html = html.replace('<div id="message"', f'<div class="standalone-note"><strong>完整單檔網頁 v{RELEASE}</strong> · 不需另外載入 CSS 或程式檔。支援自己的 UTF-8／Big5 CSV；行情在此瀏覽器計算。<noscript><br>目前預覽未允許 JavaScript，請下載本 HTML 後使用 Chrome／Edge 開啟。</noscript></div><div id="message"')
    html = html.replace('所有資料儲存於本機', '資料留在此瀏覽器')
    html = html.replace('離線運算 · TAIPEI UTC+8', '獨立網頁 · 本機計算 · UTC+8')
    html = html.replace('class="brand" href="/"', 'class="brand" href="#"')
    scripts = '<script>' + sources['csv.js'] + '</script><script>' + sources['engine.js'] + '</script><script>' + sources['local-store.js'] + '</script><script>' + bridge + '</script><script>' + sources['app.js'] + '</script>'
    html = html.replace('<script src="/csv.js" defer></script><script src="/app.js" defer></script>', scripts)
    target = output / f'naked-k-backtester-v{RELEASE}.html'
    target.write_text(html, encoding='utf-8')
    assert '<script src=' not in html and 'rel="stylesheet"' not in html, 'Standalone entry must not depend on separate files'
    # Every published entry name opens the complete document, never the server shell.
    for alias in ('index.html', 'naked-k-preview.html', 'naked-k-backtester-v1.1.html'):
        (output / alias).write_text(html, encoding='utf-8')
    files = [ROOT / 'README.md', ROOT / 'start_windows.bat', ROOT / '.gitignore', ROOT/'requirements.txt', ROOT/'requirements-dev.txt']
    for folder in ('backtester', 'static', 'tests', '.github', 'tools', 'docs', 'legacy'):
        files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    archive = output / f'naked-k-backtester-v{RELEASE}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('index.html', html.encode('utf-8'))
        for file in sorted(files):
            data = file.read_bytes()
            if file.suffix == '.bat':
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            z.writestr('naked-k-backtester/' + file.relative_to(ROOT).as_posix(), data)
        z.writestr('naked-k-backtester/standalone.html', html.encode('utf-8'))
        z.writestr('naked-k-backtester/index.html', html.encode('utf-8'))
    print(f'HTML: {target} ({target.stat().st_size:,} bytes)')
    print(f'ZIP: {archive} ({archive.stat().st_size:,} bytes)')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'artifacts')
    build(parser.parse_args().output)
