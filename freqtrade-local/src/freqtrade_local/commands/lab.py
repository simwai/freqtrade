"""Lab SSE log stream command wrapper."""

import asyncio
import logging
import signal

from freqtrade.commands.optimize_commands import start_lab as _start_lab  # noqa: F401

logger = logging.getLogger(__name__)


def start_lab(args: dict) -> None:
    """
    Start SSE log stream server (lab mode).
    """
    try:
        from freqtrade.configuration import setup_utils_configuration
        from freqtrade.enums import RunMode

        from freqtrade_local.rpc.sse_log_stream import (
            SSELogStream,
            remove_sse_logging,
            setup_sse_logging,
        )

        config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)

        logger.info("Starting freqtrade in Lab mode (SSE log stream)")

        sse_stream = SSELogStream(config)
        handler = setup_sse_logging(config, sse_stream)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _background_tasks = set()

        def _signal_handler():
            logger.info("Lab mode interrupted by user")
            task = loop.create_task(sse_stream.stop())
            _background_tasks.add(task)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            loop.run_until_complete(sse_stream.start())
            logger.info(
                "Lab mode running on http://%s:%d/logs - Press Ctrl+C to stop",
                config.get("lab_host", "127.0.0.1"),
                config.get("lab_port", 8080),
            )
            loop.run_forever()
        except KeyboardInterrupt:
            logger.info("Lab mode interrupted by user")
        finally:
            loop.run_until_complete(sse_stream.stop())
            loop.close()
            remove_sse_logging(handler)
            logger.info("Lab mode stopped")
    except Exception as e:
        logger.error("Lab mode failed: %s", e)
        raise
