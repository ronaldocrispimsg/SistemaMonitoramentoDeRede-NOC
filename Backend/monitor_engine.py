import asyncio
import logging
import os
import time

from Backend.scheduler import (
    CLEANUP_INTERVAL_SECONDS,
    MONITOR_INTERVAL_SECONDS,
    cleanup_old_data,
    get_active_host_ids,
    process_host_check,
)

logger = logging.getLogger("noc_lite.monitor_engine")


class MonitorEngine:
    def __init__(
        self,
        interval_seconds: int = MONITOR_INTERVAL_SECONDS,
        cleanup_interval_seconds: int = CLEANUP_INTERVAL_SECONDS,
        max_concurrency: int | None = None,
    ) -> None:
        self.interval_seconds = max(1, int(interval_seconds))
        self.cleanup_interval_seconds = max(60, int(cleanup_interval_seconds))
        default_concurrency = int(os.getenv("NOC_MONITOR_MAX_CONCURRENCY", "20"))
        self.max_concurrency = max(1, int(max_concurrency or default_concurrency))
        self._task: asyncio.Task | None = None
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._next_cleanup_at: float | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            logger.info("monitor loop já está em execução")
            return

        self._next_cleanup_at = time.monotonic() + self.cleanup_interval_seconds
        self._task = asyncio.create_task(self._run_loop(), name="noc-monitor-loop")
        logger.info(
            "monitor loop iniciado | interval=%ss | cleanup=%ss | max_concurrency=%s",
            self.interval_seconds,
            self.cleanup_interval_seconds,
            self.max_concurrency,
        )

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info("monitor loop cancelado com sucesso")

        self._task = None

    async def _run_loop(self) -> None:
        try:
            while True:
                cycle_start = time.monotonic()

                try:
                    await self.monitor_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("erro no ciclo global de monitoramento")

                if self._next_cleanup_at is not None and time.monotonic() >= self._next_cleanup_at:
                    await self._run_cleanup()
                    self._next_cleanup_at = time.monotonic() + self.cleanup_interval_seconds

                elapsed = time.monotonic() - cycle_start
                sleep_for = self.interval_seconds - elapsed
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    logger.warning(
                        "ciclo atrasado: duração %.2fs ultrapassou intervalo de %ss",
                        elapsed,
                        self.interval_seconds,
                    )
        except asyncio.CancelledError:
            logger.info("encerrando monitor loop")
            raise

    async def monitor_cycle(self) -> None:
        cycle_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info("ciclo iniciado em %s", cycle_ts)

        host_ids = await get_active_host_ids()
        logger.info("hosts ativos para checagem: %s", len(host_ids))

        if not host_ids:
            logger.info("ciclo finalizado: nenhum host ativo")
            return

        tasks = [asyncio.create_task(self.check_host(host_id)) for host_id in host_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        failures = 0
        for host_id, result in zip(host_ids, results):
            if isinstance(result, Exception):
                failures += 1
                logger.exception(
                    "erro na task do host id=%s",
                    host_id,
                    exc_info=result,
                )

        logger.info(
            "ciclo finalizado | total_hosts=%s | falhas=%s",
            len(host_ids),
            failures,
        )

    async def check_host(self, host_id: int) -> None:
        async with self._semaphore:
            try:
                await process_host_check(host_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("erro no processamento do host id=%s", host_id)

    async def _run_cleanup(self) -> None:
        try:
            logger.info("iniciando rotina de cleanup")
            await cleanup_old_data()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("erro na rotina de cleanup")


monitor_engine = MonitorEngine()
