"""Job worker: polls the Postgres `jobs` table (FOR UPDATE SKIP LOCKED), runs WORKER_CONCURRENCY jobs at a time.

Run as its own process in production: `python -m app.worker`. The loop never dies: every iteration is wrapped
and logged. A heartbeat file feeds the compose healthcheck.
"""
import asyncio
import logging
import signal
import time
from pathlib import Path

from app.core.config import settings
from app.core.db import get_db_context

logger = logging.getLogger("app.worker")

STALE_CHECK_S = 30
PURGE_EVERY_S = 600


def _claim() -> int | None:
    from app.modules.jobs.service import claim_next
    with get_db_context() as db:
        return claim_next(db)


def _housekeeping() -> None:
    from app.modules.documents.service import DocumentService
    from app.modules.jobs.service import requeue_stale
    with get_db_context() as db:
        requeue_stale(db)
    with get_db_context() as db:
        DocumentService(db).purge_expired_public()


class Worker:
    def __init__(self, concurrency: int | None = None) -> None:
        self.concurrency = concurrency or settings.WORKER_CONCURRENCY
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._running: set[asyncio.Task] = set()

    def start(self) -> None:
        self._task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)

    async def _run(self, job_id: int) -> None:
        from app.modules.jobs.runner import run_job
        try:
            await asyncio.to_thread(run_job, job_id)
        except Exception:
            logger.exception("job %s crashed outside the runner", job_id)

    def _heartbeat(self) -> None:
        try:
            Path(settings.WORKER_HEARTBEAT_FILE).touch()
        except OSError:
            pass

    async def loop(self) -> None:
        logger.info("worker started, concurrency %s", self.concurrency)
        last_house = 0.0
        while not self._stop.is_set():
            try:
                self._heartbeat()
                now = time.monotonic()
                if now - last_house > STALE_CHECK_S:
                    last_house = now
                    await asyncio.to_thread(_housekeeping)
                self._running = {t for t in self._running if not t.done()}
                if len(self._running) >= self.concurrency:
                    await asyncio.sleep(0.2)
                    continue
                job_id = await asyncio.to_thread(_claim)
                if job_id is None:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=settings.WORKER_POLL_S)
                    except asyncio.TimeoutError:
                        pass
                    continue
                self._running.add(asyncio.create_task(self._run(job_id)))
            except Exception:
                logger.exception("worker loop iteration failed")
                await asyncio.sleep(2)
        logger.info("worker stopping")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, worker._stop.set)
        except NotImplementedError:
            pass
    await worker.loop()
    if worker._running:
        await asyncio.gather(*worker._running, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
