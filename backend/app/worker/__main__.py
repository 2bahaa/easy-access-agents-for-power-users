"""Standalone run worker: `python -m app.worker` (set RUN_WORKER_EMBEDDED=false on the API)."""

import asyncio
import contextlib
import logging
import signal

from app.config import get_settings
from app.crypto import SecretBox
from app.db.session import create_engine, create_sessionmaker
from app.runtime.providers.registry import build_default_providers
from app.services.provider_service import ProviderResolver
from app.tools.registry import build_default_registry
from app.worker.run_worker import RunWorker

logger = logging.getLogger("app.worker")


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    worker = RunWorker(
        settings,
        create_sessionmaker(engine),
        ProviderResolver(
            build_default_providers(settings.ollama_base_url),
            SecretBox(settings.secret_encryption_key.get_secret_value()),
        ),
        build_default_registry(),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not supported on Windows
            loop.add_signal_handler(sig, stop.set)
    worker.start()
    logger.info("Run worker %s started", worker.worker_id)
    try:
        await stop.wait()
    finally:
        # Graceful stop: in-flight runs end as cancelled rather than waiting to be reaped.
        await worker.stop(cancel_runs=True)
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
