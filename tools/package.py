"""Package source and launch instructions, excluding local data and dependencies."""
import argparse
import hashlib
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_standalone import build as build_legacy


def package(output):
    output.mkdir(parents=True, exist_ok=True)
    files = [ROOT/name for name in ('README.md','index.html','start_windows.bat','.gitignore','requirements.txt','requirements-dev.txt')]
    for directory in ('backtester','static','tests','tools','docs','examples','legacy','.github'):
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    archive = output/'naked-k-backtester-v1.2-multitimeframe.zip'
    with tempfile.TemporaryDirectory() as directory:
        legacy = build_legacy(Path(directory))
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for file in sorted(files):
                content=file.read_bytes()
                if file.suffix=='.bat':content=content.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
                z.writestr('naked-k-backtester/'+file.relative_to(ROOT).as_posix(),content)
            z.writestr('naked-k-backtester/legacy/legacy-four-strategies.html',legacy.read_bytes())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        names=z.namelist()
        assert not any('/data/' in n or '/.venv/' in n or '/.git/' in n for n in names)
        assert 'naked-k-backtester/start_windows.bat' in names
        assert b'content="width=device-width' in z.read('naked-k-backtester/index.html')
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (output/(archive.name+'.sha256')).write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(f'Full application: {archive} ({archive.stat().st_size:,} bytes, {len(names)} files)')
    print(f'SHA-256: {digest}')
    return archive


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT.parent/'artifacts')
    package(parser.parse_args().output)
