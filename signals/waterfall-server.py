#!/usr/bin/env python3
"""Read-only waterfall server; never opens the SDR."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
from urllib.parse import urlsplit,parse_qs

parser = argparse.ArgumentParser()
parser.add_argument('--snapshot', type=Path, default=Path('/home/hackrf/signal-spool/live.json'))
parser.add_argument('--html', type=Path, default=Path('/usr/local/share/hackrf-waterfall/index.html'))
parser.add_argument('--port', type=int, default=8073)
args = parser.parse_args()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split('?')[0]
        if route not in ('/', '/api/live'):
            self.send_error(404)
            return
        try:
            payload = (args.html if route == '/' else args.snapshot).read_bytes()
            if route=='/api/live':
                role=parse_qs(urlsplit(self.path).query).get('receiver',['narrow'])[0]
                if role not in ('narrow','wide'):self.send_error(400);return
                data=json.loads(payload);payload=json.dumps(data.get('receivers',{}).get(role,data)).encode()
        except OSError:
            self.send_error(503, 'Waiting for spectrum measurements')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if route == '/' else 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass

ThreadingHTTPServer(('0.0.0.0', args.port), Handler).serve_forever()
