"""
SSE (Server-Sent Events) Log Stream
Provides real-time log streaming via HTTP SSE endpoint.
"""

import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from typing import Any

from aiohttp import web
from aiohttp.web import Request, StreamResponse


logger = logging.getLogger(__name__)


class SSELogStream:
    """
    SSE Log Stream handler.
    Maintains a buffer of recent log records and serves them via SSE endpoint.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.port = config.get("lab_port", 8080)
        self.host = config.get("lab_host", "127.0.0.1")
        self.max_buffer_size = config.get("lab_log_buffer_size", 1000)
        self.log_buffer: deque = deque(maxlen=self.max_buffer_size)
        self.clients: set = set()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._job_counter = 0
        self._job_id_prefix = ""

    def _generate_job_id(self, action: str, strategy: str) -> str:
        """Generate job ID in format: {action}-{strategy}-{YYYYMMDD}-{NNNN}"""
        self._job_counter += 1
        date_str = datetime.now().strftime("%Y%m%d")
        return f"{action}-{strategy}-{date_str}-{self._job_counter:04d}"

    def set_job_prefix(self, action: str, strategy: str) -> str:
        """Set job prefix and return new job ID."""
        self._job_id_prefix = f"{action}-{strategy}-{datetime.now().strftime('%Y%m%d')}-"
        self._job_counter = 0
        return self._generate_job_id(action, strategy)

    def add_log_record(self, record: logging.LogRecord) -> None:
        """Add a log record to the buffer and broadcast to SSE clients."""
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "job_id": getattr(record, "job_id", None),
        }

        # Add extra fields if present
        if hasattr(record, "action"):
            log_entry["action"] = record.action
        if hasattr(record, "strategy"):
            log_entry["strategy"] = record.strategy

        self.log_buffer.append(log_entry)

        # Broadcast to all connected SSE clients
        for client in self.clients:
            try:
                client.send(json.dumps(log_entry))
            except Exception:
                # Client disconnected, will be cleaned up on next iteration
                pass

    def _cleanup_clients(self) -> None:
        """Remove disconnected clients."""
        self.clients = {c for c in self.clients if not c.closed}

    async def _sse_handler(self, request: web.Request) -> web.StreamResponse:
        """Handle SSE connections."""
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)

        # Send initial buffer
        for entry in self.log_buffer:
            await response.write(f"data: {json.dumps(entry)}\n\n".encode())

        # Create client queue
        client_queue: asyncio.Queue = asyncio.Queue()
        self.clients.add(client_queue)

        try:
            while True:
                try:
                    entry = await asyncio.wait_for(client_queue.get(), timeout=30.0)
                    await response.write(f"data: {json.dumps(entry)}\n\n".encode())
                except asyncio.TimeoutError:
                    # Send heartbeat comment to keep connection alive
                    await response.write(b": heartbeat\n\n")
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self.clients.discard(client_queue)

        return response

    async def _broadcast_worker(self) -> None:
        """Background worker to broadcast log entries to clients."""
        while True:
            self._cleanup_clients()
            await asyncio.sleep(1)

    async def start(self) -> None:
        """Start the SSE server."""
        app = web.Application()
        app.router.add_get("/logs", self._sse_handler)
        app.router.add_get("/logs/stream", self._sse_handler)  # alias
        async def _health_handler(request: Request) -> StreamResponse:
            return web.json_response({"status": "ok"})

        app.router.add_get("/health", _health_handler)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()

        # Start broadcast worker
        asyncio.create_task(self._broadcast_worker())

        logger.info("SSE log stream started on http://%s:%d/logs", self.host, self.port)

    async def stop(self) -> None:
        """Stop the SSE server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("SSE log stream stopped")


class SSELogHandler(logging.Handler):
    """Logging handler that forwards records to SSELogStream."""

    def __init__(self, sse_stream: SSELogStream) -> None:
        super().__init__()
        self.sse_stream = sse_stream

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sse_stream.add_log_record(record)
        except Exception:
            self.handleError(record)


def setup_sse_logging(config: dict[str, Any], sse_stream: SSELogStream) -> SSELogHandler:
    """Set up SSE logging handler on root logger."""
    handler = SSELogHandler(sse_stream)
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)
    return handler


def remove_sse_logging(handler: SSELogHandler) -> None:
    """Remove SSE logging handler."""
    logging.getLogger().removeHandler(handler)
