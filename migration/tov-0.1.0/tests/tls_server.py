# A TLS server for the ALPN test (tov-patches/tests/alpn.tov): it offers h2 and accepts every
# connection, so a client sees the protocol it negotiated. Usage: tls_server.py CERT KEY
# (prints the port, then serves until killed).
import socket
import ssl
import sys
import threading

cert, key = sys.argv[1], sys.argv[2]
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(cert, key)
ctx.set_alpn_protocols(["h2"])
ls = socket.socket()
ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
ls.bind(("127.0.0.1", 0))
ls.listen(16)
print(ls.getsockname()[1], flush=True)


def serve(raw):
    try:
        s = ctx.wrap_socket(raw, server_side=True)
        while s.recv(1024):
            pass
    except OSError:
        pass
    finally:
        raw.close()


while True:
    c, _ = ls.accept()
    threading.Thread(target=serve, args=(c,), daemon=True).start()
