"""FastAPI / Uvicorn entry point with a controllable server adapter for tests."""
import argparse
import socket
import threading
from pathlib import Path
import uvicorn
from .api import create_app

class LocalServer:
    def __init__(self, host, port, db_path):
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.socket.bind((host,port));self.socket.listen(128)
        self.server_port=self.socket.getsockname()[1]
        self.server=uvicorn.Server(uvicorn.Config(create_app(db_path),host=host,port=self.server_port,log_level='warning',access_log=False,lifespan='off'))
        self.stopped=threading.Event()
    def serve_forever(self):
        try:self.server.run(sockets=[self.socket])
        finally:self.stopped.set()
    def shutdown(self):
        self.server.should_exit=True;self.stopped.wait(10)
    def server_close(self):self.socket.close()

def create_server(host='127.0.0.1',port=8000,db_path='data/backtester.sqlite3'):
    return LocalServer(host,port,db_path)

def main():
    parser=argparse.ArgumentParser(description='裸 K Lab FastAPI 本機服務')
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--db',default=str(Path(__file__).resolve().parents[1]/'data'/'backtester.sqlite3'))
    parser.add_argument('--open-browser',action='store_true');args=parser.parse_args()
    server=create_server(args.host,args.port,args.db)
    print(f'裸 K Lab FastAPI 已啟動，連接埠 {server.server_port}。Ctrl+C 結束。',flush=True)
    if args.open_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{server.server_port}')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
