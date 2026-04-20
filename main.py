import re
import aiohttp
from fastapi import FastAPI
import uvicorn
import sys
import os
import logging
from dotenv import load_dotenv

load_dotenv()


from private import cid_by_name_private, cname_private
from utils import _env
from userbot import (
    channel_counts,
    channel_info,
    channel_managers,
    name_to_id,
    user_info_edge,
    who_installed_it,
)


logging.basicConfig(level=logging.INFO, format="[%(name)s]: %(message)s")


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
        # private
        name = (await cname_private(id)).get("name", "unknown")
        ret["name"] = name
        return ret

    # public below
    ret["counts"] = (await channel_counts(id)).get("data", {})
    ret["managers"] = managers.get("data", [])
    if not (info := await channel_info(id)).get("error", {}):
        ret.update(info.get("data", {}))
    return ret


@app.get("/cid/{id}")
async def channel_by_id(id: str):
    return await channel(id)


@app.get("/cname/{name}")
async def channel_by_name(name: str):
    data = await name_to_id(name)
    if not (err := data.get("error")):
        return await channel(data.get("data", {}).get("id"))
    id = (await cid_by_name_private(name)).get("id", "")
    if not id:
        return {"error": "nonexistent"}
    return await channel(id)


@app.get("/channel/{id}")
async def channel_info_public(id: str):
    if not re.fullmatch(r"C[A-Z0-9]{6,}", id):
        return await channel_by_name(id)
    return await channel(id)


@app.get("/user/{id}")
async def user_info(id: str):
    if not re.fullmatch(r"U[A-Z0-9]{6,}", id):
        return {"error": "invalid user ID"}
    data = {}
    if not (userinfo := await user_info_edge(id)).get("error"):
        data["user"] = userinfo.get("data", {})
    if userinfo.get("data", {}).get("is_bot"):
        app_id = userinfo.get("data", {}).get("app_id")
        data["installers"] = await who_installed_it(app_id) if app_id else []
    return data


@app.get("/app/{id}")
async def app_info(id: str):
    if not re.fullmatch(r"A[A-Z0-9]{6,}", id):
        return {"error": "invalid app ID"}
    data = {}
    if (installedby := await who_installed_it(id)) is not None:
        data["installers"] = installedby
        data["user"] = (await user_info_edge(installedby[0].get("id", ""))).get(
            "data", {}
        )
    return data if data else {"error": "nonexistent"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", reload="--reload" in sys.argv)
