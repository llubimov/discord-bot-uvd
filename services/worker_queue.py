"""
Очередь задач для тяжёлых операций (БД и т.п.).
Воркер обрабатывает задачи в одном потоке по одной — снижает конкуренцию за SQLite и нагрузку на event loop.
"""
import asyncio
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Максимум задач в очереди, чтобы при всплеске не раздувать память
MAX_QUEUE_SIZE = 2000


class WorkerQueue:
    def __init__(self, max_size: int = MAX_QUEUE_SIZE):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._worker_task: asyncio.Task | None = None
        self._running = False

    def submit(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> asyncio.Future[T]:
        """Поставить задачу в очередь и вернуть Future с результатом. await future — получить результат."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        try:
            self._queue.put_nowait((fn, args, kwargs, future))
        except asyncio.QueueFull:
            future.set_exception(RuntimeError("Очередь задач переполнена"))
        return future

    def submit_fire(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Поставить задачу в очередь без ожидания результата (fire-and-forget)."""
        try:
            self._queue.put_nowait((fn, args, kwargs, None))
        except asyncio.QueueFull:
            logger.warning("Очередь воркера переполнена, задача %s пропущена", fn.__name__)

    async def _run_worker(self) -> None:
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            fn, args, kwargs, future = item
            try:
                result = await asyncio.to_thread(fn, *args, **kwargs)
                if future is not None and not future.done():
                    future.set_result(result)
            except Exception as e:
                if future is not None and not future.done():
                    future.set_exception(e)
                else:
                    logger.warning("Воркер: ошибка в задаче %s: %s", getattr(fn, "__name__", fn), e, exc_info=True)

    def start(self) -> None:
        if self._worker_task is not None:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._run_worker())
        logger.info("Воркер очереди задач запущен")

    def stop(self) -> None:
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            self._worker_task = None
        logger.info("Воркер очереди задач остановлен")


# Глобальный экземпляр, запускается из main
worker: WorkerQueue | None = None


def get_worker() -> WorkerQueue:
    if worker is None:
        raise RuntimeError("WorkerQueue не инициализирован. Вызовите worker_queue.init_worker() при старте бота.")
    return worker


def init_worker(max_size: int = MAX_QUEUE_SIZE) -> WorkerQueue:
    global worker
    worker = WorkerQueue(max_size=max_size)
    return worker
