"""WIMI MCP Server bridge operations — start/stop SSE server from the GUI."""

import json
import threading

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class McpServerBridgeMixin:
    """Bridge mixin for MCP SSE server lifecycle control."""

    _mcp_thread: threading.Thread = None
    _mcp_uvicorn_server = None  # uvicorn.Server instance
    _mcp_running: bool = False
    _mcp_port: int = None
    _mcp_error: str = None

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def startMcpServer(self, params_json: str) -> str:
        """Start the MCP SSE server on the configured port."""
        if self._mcp_running:
            return serialize_response(True, data={
                'running': True,
                'port': self._mcp_port,
                'url': f'http://127.0.0.1:{self._mcp_port}/sse'
            })

        try:
            params = json.loads(params_json)
            port = int(params.get('port', 8000))

            if port < 1024 or port > 65535:
                return serialize_response(False, error='Port must be between 1024 and 65535')

            # Test if port is available before starting
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                result = sock.connect_ex(('127.0.0.1', port))
                if result == 0:
                    return serialize_response(
                        False,
                        error=f'Port {port} is already in use. Choose a different port.'
                    )

            self._mcp_error = None
            self._mcp_port = port

            # Start server in a daemon thread
            self._mcp_thread = threading.Thread(
                target=self._run_mcp_sse_server,
                args=(port,),
                daemon=True,
                name='mcp-sse-server'
            )
            self._mcp_thread.start()

            # Brief wait to catch immediate startup errors
            self._mcp_thread.join(timeout=1.0)

            if self._mcp_error:
                self._mcp_running = False
                return serialize_response(False, error=self._mcp_error)

            if not self._mcp_thread.is_alive():
                self._mcp_running = False
                return serialize_response(False, error='MCP server failed to start')

            self._mcp_running = True
            return serialize_response(True, data={
                'running': True,
                'port': port,
                'url': f'http://127.0.0.1:{port}/sse'
            })

        except Exception as e:
            self._mcp_running = False
            return serialize_response(False, error=f'Failed to start MCP server: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def stopMcpServer(self) -> str:
        """Stop the running MCP SSE server."""
        if not self._mcp_running or self._mcp_uvicorn_server is None:
            self._mcp_running = False
            return serialize_response(True, data={'running': False})

        try:
            self._mcp_uvicorn_server.should_exit = True

            if self._mcp_thread and self._mcp_thread.is_alive():
                self._mcp_thread.join(timeout=5)

            self._mcp_running = False
            self._mcp_uvicorn_server = None
            self._mcp_thread = None

            return serialize_response(True, data={'running': False})

        except Exception as e:
            return serialize_response(False, error=f'Failed to stop MCP server: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def getMcpServerStatus(self) -> str:
        """Check if the MCP server is currently running."""
        # Verify the thread is actually still alive
        if self._mcp_running and self._mcp_thread and not self._mcp_thread.is_alive():
            self._mcp_running = False
            self._mcp_uvicorn_server = None
            self._mcp_thread = None

        data = {
            'running': self._mcp_running,
            'port': self._mcp_port,
        }
        if self._mcp_running and self._mcp_port:
            data['url'] = f'http://127.0.0.1:{self._mcp_port}/sse'
        if self._mcp_error:
            data['error'] = self._mcp_error

        return serialize_response(True, data=data)

    def _run_mcp_sse_server(self, port: int):
        """Run the MCP SSE server in a background thread with its own event loop."""
        import asyncio

        try:
            import uvicorn
            from mcp_server import mcp as mcp_instance

            # Configure the FastMCP instance with the requested port
            mcp_instance.settings.host = '127.0.0.1'
            mcp_instance.settings.port = port

            starlette_app = mcp_instance.sse_app()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            config = uvicorn.Config(
                starlette_app,
                host='127.0.0.1',
                port=port,
                log_level='warning',
            )
            self._mcp_uvicorn_server = uvicorn.Server(config)
            loop.run_until_complete(self._mcp_uvicorn_server.serve())

        except OSError as e:
            self._mcp_error = f'Port {port} is already in use: {e}'
            self._mcp_running = False
        except Exception as e:
            self._mcp_error = f'MCP server error: {e}'
            self._mcp_running = False
