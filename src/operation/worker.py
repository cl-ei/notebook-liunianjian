import asyncio
import logging
import time
import traceback
from multiprocessing import Process, Queue
from queue import Empty
from src.operation.blog import publish_blog


_global_communication = [
    Queue(),  # task and control queue
]

_process = []


def worker_wrapper(index: int, q: Queue):
    logging.info(f"\t worker {index} started.")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    while True:
        try:
            task = q.get_nowait()
        except Empty:
            time.sleep(1)
            continue

        try:
            act = task["act"]
            if act == "stop":
                q.put_nowait(task)
                logging.info(f"worker {index} received stop cmd, exit")
                return

            if act == "publish_blog":
                email = task["email"]
                version = task["version"]
                logging.debug(f"worker {index} received task: {act}, args: {email}, {version}")

                loop.run_until_complete(publish_blog(email=email, version=version))
                pending_tasks = asyncio.all_tasks(loop)
                if pending_tasks:
                    loop.run_until_complete(asyncio.gather(*pending_tasks, return_exceptions=True))
                logging.debug(f"worker {index} blog publish complete, args: {email}, {version}")

        except Exception as e:
            logging.error(f"error happened in worker {index}: {e}\n{traceback.format_exc()}")


def start(count: int = 2):
    q = _global_communication[0]
    for i in range(count):
        p = Process(target=worker_wrapper, args=(i, q))
        p.start()
        _process.append(p)
    logging.info(f"worker started, total: {count}")


def stop():
    global _global_communication
    global _process

    q = _global_communication[0]
    q.put_nowait({"act": "stop"})
    p: Process
    for p in _process:
        p.join()
    _process = []
    logging.info("worker stopped.")


def create_task_publish_blog(email: str, version: str) -> bool:
    q = _global_communication[0]
    try:
        q.put_nowait({
            "act": "publish_blog",
            "email": email,
            "version": version,
        })
        return True

    except Exception as e:
        logging.error(f"error happened in create_task_publish_blog: {e}\n{traceback.format_exc()}")
    return False
