# An HTTPS server that requires a client certificate, for tov-patches/tests/client_cert.tov (patch 0015).
# Usage: client_cert_server.py CERT KEY CLIENT_CAS. Prints the port, then answers every request with the
# common name of the client's certificate, until killed. A connection without a trusted client
# certificate fails its handshake.
import socket
import ssl
import sys
import threading

cert, key, cas = sys.argv[1], sys.argv[2], sys.argv[3]
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(cert, key)
ctx.verify_mode = ssl.CERT_REQUIRED
ctx.load_verify_locations(cafile=cas)
ls = socket.socket()
ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
ls.bind(("127.0.0.1", 0))
ls.listen(16)
print(ls.getsockname()[1], flush=True)


def serve(raw):
    try:
        s = ctx.wrap_socket(raw, server_side=True)
        cn = ""
        for rdn in s.getpeercert().get("subject", ()):
            for k, v in rdn:
                if k == "commonName":
                    cn = v
        data = b""
        while True:
            while b"\r\n\r\n" not in data:
                c = s.recv(4096)
                if not c:
                    return
                data += c
            data = data.split(b"\r\n\r\n", 1)[1]
            body = cn.encode()
            s.sendall(b"HTTP/1.1 200 OK\r\ncontent-length: %d\r\n\r\n%s" % (len(body), body))
    except (OSError, ssl.SSLError):
        pass
    finally:
        raw.close()


while True:
    c, _ = ls.accept()
    threading.Thread(target=serve, args=(c,), daemon=True).start()
