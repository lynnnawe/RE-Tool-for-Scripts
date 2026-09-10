from http.server import BaseHTTPRequestHandler, HTTPServer

HOST, PORT = "127.0.0.1", 8787

class Echo(BaseHTTPRequestHandler):
    def _echo(self):
        body_lines = []
        print("\n" + "=" * 70)
        print(f"{self.command} {self.path}  from {self.client_address[0]}")
        print("=" * 70)
        for name, value in self.headers.items():
            line = f"{name}: {value}"
            print("  " + line)
            body_lines.append(line)
        print("=" * 70)

        body = "\n".join(body_lines).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _echo
    do_POST = _echo
    do_PUT = _echo

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    print(f"Header echo server listening on http://{HOST}:{PORT}/")
    print("Set ECHO_TEST = true in Potassium_SelfAudit.luau and run it.")
    print("Ctrl+C to stop.\n")
    try:
        HTTPServer((HOST, PORT), Echo).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
