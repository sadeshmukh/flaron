import aiohttp
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


async def cname_private(id: str) -> dict:
    url = f"{PRIVATECHANNEL_BASE}/channel/{id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as res:
            data = await res.json()
            if not data.get("success") and not data.get("ok"):
                return {"error": "channel doesn't exist"}

            return data


async def cid_by_name(name: str) -> dict:
    url = f"{PRIVATECHANNEL_BASE}/fakepostchannel/?name={name}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as res:
            data = await res.json()
            if not data.get("success"):
                return {"error": "channel doesn't exist"}

            return data


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


async def channel(id: str):
    ret = {"id": id}

    if (
        "error" in (managers := await channel_managers(id))
        and managers["error"] == "nonexistent"
    ):
        ret["error"] = "nonexistent"
        return ret

    elif "error" in managers and managers["error"] == "private":
        name = (await cname_private(id)).get("name", "unknown")
        ret["name"] = name
        return ret

    ret["counts"] = (await channel_counts(id)).get("data", {})
    ret["managers"] = managers.get("data", [])
    return ret


@app.get("/cid/{id}")
async def channel_by_id(id: str):
    return await channel(id)


@app.get("/cname/{name}")
async def channel_by_name(name: str):
    id = (await cid_by_name(name)).get("id", "")
    if not id:
        return {"error": "nonexistent"}
    return await channel(id)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", reload="--reload" in sys.argv)
