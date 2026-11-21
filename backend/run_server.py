"""
Run Gativa Backend with Dual-Stack (IPv4 + IPv6) socket binding.
Guarantees compatibility with both http://localhost:8000 and http://127.0.0.1:8000 on Windows.
"""
import sys
import socket
import uvicorn
from main import app

"""
Run Gativa Backend with safe loopback binding in development and explicit production configuration.
Guarantees local isolation on 127.0.0.1 by default, requiring explicit configuration for external interfaces.
"""
import os
import sys
import logging
import uvicorn
from main import app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gativa.server")


def run():
    port = int(os.environ.get("PORT", 8000))
    configured_host = os.environ.get("HOST", "").strip()
    allow_external = os.environ.get("ALLOW_EXTERNAL_BINDING", "false").lower() in ("true", "1", "yes")
    is_prod = os.environ.get("ENVIRONMENT", "development").lower() == "production"

    if configured_host:
        host = configured_host
    elif allow_external or is_prod:
        host = "0.0.0.0"
    else:
        host = "127.0.0.1"

    if host in ("0.0.0.0", "::"):
        logger.warning(
            "SECURITY WARNING: Server is binding to external network interfaces (%s:%d). "
            "Ensure this service is behind a reverse proxy with TLS and authentication.",
            host,
            port,
        )
    else:
        logger.info("Server bound securely to loopback interface (%s:%d) for local development.", host, port)

    uvicorn.run("main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()

if __name__ == "__main__":
    run()
