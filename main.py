from fastapi import FastAPI
import uvicorn
import sys
import os
import logging
from dotenv import load_dotenv

load_dotenv()


from utils import _env
from userbot import channel_counts, channel_managers


logging.basicConfig(level=logging.INFO, format="[%(name)s]: %(message)s")

PRIVATECHANNEL_BASE = _env("PRIVATECHANNEL_BASE")

app = FastAPI()


@app.get("/hello")
async def hello():
    return {"message": "Hello, World!"}


@app.get("/cman/{id}")
async def cman(id: str):
    return await channel_managers(id)


@app.get("/ccount/{id}")
async def ccount(id: str):
    return await channel_counts(id)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", reload="--reload" in sys.argv)
