"""Windows-friendly first-run environment creation and pinned installation."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser=argparse.ArgumentParser(description='Prepare and start the local backtester.')
    parser.add_argument('--check',action='store_true',help='Install/check dependencies without starting the service.')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    environment = root/'.venv'
    executable = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if sys.version_info < (3,11):
        raise SystemExit('Python 3.11 or newer is required.')
    if not executable.exists():
        print('Preparing the local Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    requirements = root/'requirements.txt'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = environment/'naked-k-requirements.sha256'
    working = subprocess.run([str(executable),'-c','import fastapi, uvicorn'],capture_output=True).returncode == 0
    if not working or not marker.exists() or marker.read_text() != digest:
        print('Installing pinned application dependencies (Internet required on first launch)...',flush=True)
        subprocess.run([str(executable),'-m','pip','install','--disable-pip-version-check','--cache-dir',str(environment/'pip-cache'),'--index-url','https://pypi.org/simple','-r',str(requirements)],cwd=root,check=True)
        marker.write_text(digest)
    if args.check:
        print('Application dependencies are ready.',flush=True)
        return 0
    command=[str(executable),'-m','backtester.server','--port',str(args.port)]
    if not args.no_browser:command.append('--open-browser')
    return subprocess.call(command,cwd=root)


if __name__ == '__main__':
    try: raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print('Setup failed. Check the command output above; no validation was disabled.',file=sys.stderr)
        raise SystemExit(error.returncode)
