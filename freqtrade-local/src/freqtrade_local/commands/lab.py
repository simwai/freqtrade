"""Lab SSE log stream command wrapper."""

import argparse
import asyncio
import logging
import signal
import sys

logger = logging.getLogger(__name__)


def start_lab(args: list[str] | None = None) -> None:
    """
    Start SSE log stream server (lab mode).
    """
    parser = argparse.ArgumentParser(description="Freqtrade Lab mode (SSE log stream)")
    parser.add_argument("--port", type=int, default=None, help="Port for the SSE log stream")

    # Handle being called via freqtrade CLI (args may be a Namespace)
    if args is not None and not isinstance(args, list):
        # args is a Namespace object from freqtrade's argument parser
        port = getattr(args, "port", None)
        if port is not None:
            args = [f"--port={port}"]
        else:
            args = None

    cli_args = parser.parse_args(args)

    try:
        from freqtrade.configuration import setup_utils_configuration
        from freqtrade.enums import RunMode

        from freqtrade_local.rpc.sse_log_stream import (
            SSELogStream,
            remove_sse_logging,
            setup_sse_logging,
        )

        config = setup_utils_configuration({}, RunMode.UTIL_NO_EXCHANGE)
        if cli_args.port is not None:
            config["lab_port"] = cli_args.port

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


if __name__ == "__main__":
    start_lab()
