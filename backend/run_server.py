"""
Run Gativa Backend with Dual-Stack (IPv4 + IPv6) socket binding.
Guarantees compatibility with both http://localhost:8000 and http://127.0.0.1:8000 on Windows.
"""
import sys
import socket
import uvicorn
from main import app

def run():
    port = 8000
    host = "::"

    # Create dual-stack socket for Windows
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Disable IPV6_V6ONLY to accept both IPv4 and IPv6 connections
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.bind((host, port))
        sock.listen(128)
        print(f"Dual-stack listening socket established on [{host}]:{port} (IPv4 + IPv6)")
        config = uvicorn.Config(app, log_level="info", access_log=True)
        server = uvicorn.Server(config)
        server.run(sockets=[sock])
    except Exception as exc:
        print(f"Dual-stack fallback to IPv4 0.0.0.0 due to: {exc}")
        uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")

if __name__ == "__main__":
    run()
