from __future__ import annotations

import logging
from threading import Event, Thread

from era5_fetch.core.config import Config
from era5_fetch.core.validation import previous_month
from era5_fetch.services.queue_service import QueueService


class MonthlyScheduler:
    def __init__(
        self,
        config: Config,
        queue: QueueService,
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._queue = queue
        self._logger = logger
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if not self._config.scheduler_enabled or self.is_running:
            return
        self._thread = Thread(target=self._run, name="era5-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def trigger_once(self) -> None:
        if self._ensure_bootstrap_window():
            return
        year, month = previous_month()
        self._logger.info("Scheduler triggered year=%s month=%s", year, month)
        self._queue.download_month(year, month)

    def _ensure_bootstrap_window(self) -> bool:
        newest_year, newest_month = previous_month()
        months = _month_window(newest_year, newest_month, self._config.scheduler_bootstrap_months)
        missing = [(year, month) for year, month in months if not self._queue.is_cached(year, month)]
        if not missing:
            return False
        self._logger.info(
            "Scheduler bootstrap triggered missing_months=%s newest_year=%s newest_month=%s",
            len(missing),
            newest_year,
            newest_month,
        )
        self._queue.ensure_months(missing)
        return True

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.trigger_once()
            except Exception:
                self._logger.exception("Scheduler cycle failed")
            self._stop_event.wait(self._config.scheduler_check_interval_seconds)


def _month_window(newest_year: int, newest_month: int, count: int) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    year, month = newest_year, newest_month
    for _ in range(max(count, 1)):
        months.append((year, month))
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return list(reversed(months))
