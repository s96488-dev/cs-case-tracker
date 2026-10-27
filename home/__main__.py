import logging

import uvicorn

from . import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
uvicorn.run("home.api:app", host=config.API_HOST, port=config.API_PORT)
