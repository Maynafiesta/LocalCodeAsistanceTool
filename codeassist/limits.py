import asyncio
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request


class InferenceGate:
    """One process, bounded admission; holds a permit until the response stream closes."""

    def __init__(self, concurrency: int, queue_size: int):
        self._semaphore = asyncio.Semaphore(concurrency)
        self.capacity = concurrency + queue_size
        self.outstanding = 0
        self.active = 0
        self.rejected = 0
        self.completed = 0

    @asynccontextmanager
    async def slot(self, timeout: float):
        # No await between checking and incrementing: atomic within the event loop.
        if self.outstanding >= self.capacity:
            self.rejected += 1
            raise HTTPException(429, "Inference queue is full", headers={"Retry-After": "2"})
        self.outstanding += 1
        acquired = False
        try:
            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout)
            except TimeoutError:
                self.rejected += 1
                raise HTTPException(
                    429, "Inference queue wait expired", headers={"Retry-After": "2"}
                )
            acquired = True
            self.active += 1
            yield
            self.completed += 1
        finally:
            self.outstanding -= 1
            if acquired:
                self.active -= 1
                self._semaphore.release()

    def snapshot(self):
        return {
            "active": self.active,
            "queued": self.outstanding - self.active,
            "rejected": self.rejected,
            "completed": self.completed,
        }


async def while_connected(request: Request, operation):
    """Cancel queue/upstream work when a VSCode request is abandoned."""
    task = asyncio.create_task(operation)
    stopped = asyncio.Event()

    async def disconnected():
        while not stopped.is_set() and not await request.is_disconnected():
            await asyncio.sleep(0.1)

    monitor = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((task, monitor), return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return await task
        raise HTTPException(499, "Client disconnected")
    finally:
        stopped.set()
        monitor.cancel()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, monitor, return_exceptions=True)
