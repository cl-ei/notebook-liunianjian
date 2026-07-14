import sys
import uvicorn
import logging
from src.operation import worker
from src.framework.config import DEBUG, LOG_FILE

import multiprocessing
multiprocessing.set_start_method("spawn", force=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s]: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)

logging.getLogger("asyncio").setLevel(logging.INFO)


if __name__ == "__main__":
    worker.start()
    uvicorn.run("src.main:app", port=10091, host="0.0.0.0", workers=1, reload=False)
    worker.stop()
