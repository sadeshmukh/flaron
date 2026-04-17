from fastapi import FastAPI
import uvicorn
import sys
import os
from utils import _env
import logging

logging.basicConfig(level=logging.INFO, format="[%(name)s]: %(message)s")

PRIVATECHANNEL_BASE = _env("PRIVATECHANNEL_BASE")

app = FastAPI()


@app.get("/hello")
async def hello():
    return {"message": "Hello, World!"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", reload="--reload" in sys.argv)
