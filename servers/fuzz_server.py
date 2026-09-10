import socket, struct, threading, base64, hashlib, sys

HOST, PORT = "127.0.0.1", 8790
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def http_case(path):
    if path.startswith("/ok"):
        body = b"hello"
        return (b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nContent-Type: text/plain\r\n\r\n" + body)

    if path.startswith("/huge-header"):
        return (b"HTTP/1.1 200 OK\r\nX-Big: " + b"A" * (2 * 1024 * 1024) + b"\r\nContent-Length: 0\r\n\r\n")

    if path.startswith("/many-headers"):
        hdrs = b"".join(b"X-H%d: v\r\n" % i for i in range(50000))
        return b"HTTP/1.1 200 OK\r\n" + hdrs + b"Content-Length: 0\r\n\r\n"

    if path.startswith("/negative-length"):
        return b"HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\nZ"

    if path.startswith("/overflow-length"):
        return b"HTTP/1.1 200 OK\r\nContent-Length: 18446744073709551615\r\n\r\nZ"

    if path.startswith("/lying-length"):
        return b"HTTP/1.1 200 OK\r\nContent-Length: 104857600\r\n\r\nABCD"

    if path.startswith("/bad-chunk"):
        return b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nFFFFFFFFFFFFFFFF\r\nAB"

    if path.startswith("/no-status"):
        return b"\r\n\r\ngarbage without a status line"

    if path.startswith("/nulls"):
        return b"HTTP/1.1 200 OK\r\nX-N: a\x00\x00\x00b\r\nContent-Length: 3\r\n\r\n\x00\x01\x02"

    if path.startswith("/split-forever"):
        return b"HTTP/1.1 200 OK\r\nX-Drip: 1"

    if path.startswith("/deep-json"):
        depth = 20000
        body = (b"[" * depth) + (b"]" * depth)
        return (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(body)) + body

    if path.startswith("/bad-utf8"):
        body = b"\xff\xfe\x80\x81 invalid utf8 \xc0\xc1"
        return (b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body)) + body

    return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"

def handle_http(conn, first):
    try:
        line = first.split(b"\r\n", 1)[0]
        parts = line.split(b" ")
        path = parts[1].decode("latin1") if len(parts) > 1 else "/"
        print(f"  [HTTP] {path}")
        resp = http_case(path)
        if path.startswith("/split-forever"):
            conn.sendall(resp)
            return
        conn.sendall(resp)
    except Exception as e:
        print("  [HTTP] error:", e)

def ws_accept_key(key):
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()

def ws_frame(opcode, payload, mask=False, fake_len=None):
    b0 = 0x80 | opcode
    n = len(payload) if fake_len is None else fake_len
    out = bytes([b0])
    if n < 126:
        out += bytes([n])
    elif n < 65536:
        out += bytes([126]) + struct.pack(">H", n)
    else:
        out += bytes([127]) + struct.pack(">Q", n)
    out += payload
    return out

WS_CASES = {
    "normal":        lambda: ws_frame(0x1, b"hi"),
    "len126lie":     lambda: ws_frame(0x1, b"AB", fake_len=126),
    "len127huge":    lambda: ws_frame(0x1, b"AB", fake_len=0xFFFFFFFF),
    "big2mb":        lambda: ws_frame(0x1, b"A" * (2 * 1024 * 1024)),
    "badutf8":       lambda: ws_frame(0x1, b"\xff\xfe\x80 bad"),
    "empty":         lambda: ws_frame(0x1, b""),
    "reservedop":    lambda: ws_frame(0xB, b"x"),
    "nulls":         lambda: ws_frame(0x1, b"a\x00\x00b"),
    "len64overflow": lambda: ws_frame(0x1, b"AB", fake_len=0xFFFFFFFFFFFFFFFF),
}

def handle_ws(conn, req):
    key, path = None, "/"
    for i, l in enumerate(req.split(b"\r\n")):
        if i == 0:
            p = l.split(b" ")
            if len(p) > 1:
                path = p[1].decode("latin1")
        if l.lower().startswith(b"sec-websocket-key:"):
            key = l.split(b":", 1)[1].strip().decode()
    if not key:
        conn.close(); return
    accept = ws_accept_key(key)
    conn.sendall(
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
    )
    case = path.lstrip("/") or "normal"
    maker = WS_CASES.get(case)
    print(f"  [WS] {case}")
    try:
        if maker:
            conn.sendall(maker())
        else:
            conn.sendall(ws_frame(0x1, b"?"))
        conn.settimeout(1.5)
        try:
            conn.recv(1024)
        except Exception:
            pass
    except Exception as e:
        print("  [WS] send error:", e)

def serve(conn, addr):
    try:
        conn.settimeout(5)
        data = conn.recv(65536)
        if not data:
            return
        if b"upgrade: websocket" in data.lower() or b"Upgrade: websocket" in data:
            handle_ws(conn, data)
        else:
            handle_http(conn, data)
    except Exception as e:
        print("  conn error:", e)
    finally:
        try: conn.close()
        except Exception: pass

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(16)
    print(f"Potassium fuzz server on http://{HOST}:{PORT}/  and  ws://{HOST}:{PORT}/")
    print("Run potassium_fuzz_harness.luau in Potassium. Ctrl+C to stop.\n")
    try:
        while True:
            conn, addr = s.accept()
            threading.Thread(target=serve, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nstopped.")

if __name__ == "__main__":
    main()
