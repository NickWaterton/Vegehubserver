#!/usr/bin/env python3

from http.server import BaseHTTPRequestHandler, HTTPServer
import logging

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        logging.info(f"POST received")
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        logging.info(f"POST request body:\n{post_data.decode('utf-8')}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
        
    def do_GET(self):
        logging.info(f"GET request,\nPath: {self.path}\nHeaders:\n{self.headers}")
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"GET request received")

def run(address, port):
    logging.basicConfig(level=logging.INFO)
    server_address = (address, port)
    httpd = HTTPServer(server_address, RequestHandler)
    logging.info(f'Starting server on {address}:{port}')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info('Stopping server')

if __name__ == '__main__':
    run('localhost', 8061)
