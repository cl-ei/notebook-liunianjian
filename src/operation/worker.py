import asyncio
import logging
import time
import traceback
from multiprocessing import Process, Queue
from queue import Empty
from src.operation.site.generator import StaticSiteGenerator


_global_communication = []  # task and control queue


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
                logging.info(f"worker {index} received task: {act}, args: {email}")

                loop.run_until_complete(StaticSiteGenerator(email).gen())
                pending_tasks = asyncio.all_tasks(loop)
                if pending_tasks:
                    loop.run_until_complete(asyncio.gather(*pending_tasks, return_exceptions=True))
                logging.info(f"worker {index} generate static site complete, args: {email}")

        except Exception as e:
            logging.error(f"error happened in worker {index}: {e}\n{traceback.format_exc()}")


def start(count: int = 2):
    global _global_communication

    q = Queue()
    _global_communication.append(q)

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


def create_task_publish_blog(email: str) -> bool:
    global _global_communication

    if not _global_communication:
        return False

    q = _global_communication[0]
    try:
        q.put_nowait({"act": "publish_blog", "email": email})
        logging.info(f"current queue length: {q.qsize()}")
        return True

    except Exception as e:
        logging.error(f"error happened in create_task_publish_blog: {e}\n{traceback.format_exc()}")
    return False
