"""ConnectionManager.cancel_task: the stop button's backend half (#157)."""

import asyncio

from api.routes.chat import ConnectionManager


def test_cancel_task_stops_the_task_and_clears_its_entry():
    manager = ConnectionManager()
    cancelled = []

    async def process_task():
        # Mirrors chat.py's process_task: swallows the cancel, then its finally
        # removes the registry entry before cancel_task gets control back.
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(True)
        finally:
            manager.running_tasks.pop("t1", None)

    async def scenario():
        task = asyncio.create_task(process_task())
        manager.register_task("t1", task)
        await asyncio.sleep(0)  # let the task start and block on the sleep
        await manager.cancel_task("t1")

    asyncio.run(scenario())
    assert cancelled == [True]
    assert "t1" not in manager.running_tasks


def test_cancel_task_for_unknown_thread_is_a_no_op():
    asyncio.run(ConnectionManager().cancel_task(None))
