"""Entry point: python -m src.web [--port PORT] [--host HOST] [--mcp-port PORT]"""
import argparse
import logging
import subprocess
import sys
import atexit
import signal

import uvicorn

logger = logging.getLogger("context-pilot")


_mcp_process = None


def _start_mcp(port: int, host: str = "0.0.0.0") -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.interfaces.mcp_server",
         "--transport", "sse", "--host", host, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Register in Claude config
    from src.core.claude_config import register_mcp
    register_mcp(port=port, transport="sse")
    return proc


def _cleanup():
    global _mcp_process
    from src.core.claude_config import deregister_mcp
    deregister_mcp()
    if _mcp_process and _mcp_process.poll() is None:
        _mcp_process.terminate()
        _mcp_process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="Context Pilot Web Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Web UI port (default: 8080)")
    parser.add_argument("--mcp-port", type=int, default=8400, help="MCP SSE port (default: 8400)")
    parser.add_argument("--no-mcp", action="store_true", help="Don't start MCP server")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    global _mcp_process
    if not args.no_mcp:
        _mcp_process = _start_mcp(args.mcp_port, args.host)
        logger.info("MCP Server (SSE) started on port %d", args.mcp_port)

    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(0)))

    logger.info("Web UI: http://%s:%d", args.host, args.port)
    uvicorn.run("src.web.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
