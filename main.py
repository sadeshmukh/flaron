import re
import aiohttp
from contextlib import asynccontextmanager
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
    emoji_info,
    fetch_commands,
    channel_counts,
    channel_info,
    channel_managers,
    name_to_id,
    promote_member,
    user_info_edge,
    install_info,
    app_info,
)


logging.basicConfig(level=logging.INFO, format="FLARON [%(name)s]: %(message)s")
logger = logging.getLogger("main")

commands: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global commands
    if (data := await fetch_commands()).get("error"):
        logger.error(f"app commands error: {data.get('error')}")
        exit(1)
    commands = data.get("data", {})
    if not commands:
        logger.warning("commands not found, oop")
        exit(1)
    yield


# struct: {command name -> {name, usage, description, app_name, app_id,
# icons: {image_32, image_48, image_64, image_72}}}
app = FastAPI(lifespan=lifespan)


@app.get("/hello")
async def hello():
    return {"message": "Hello, World!"}


@app.get("/command/{name}")
async def command_info(name: str):
    cmd = commands.get(name.strip("/"))
    if not cmd:
        return {"error": "command not found"}
    return cmd


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
        install_info_data = await install_info(app_id)
        if install_info_data.get("error"):
            data["installers"] = []
        else:
            data["installers"] = install_info_data.get("data", {}).get("installers", [])
            data["creator_id"] = install_info_data.get("data", {}).get("creator", {})

    return data


@app.get("/app/{id}")
async def _app_info(id: str):
    if not re.fullmatch(r"A[A-Z0-9]{6,}", id):
        return {"error": "invalid app ID"}
    data = {}
    if (install_info_data := (await install_info(id)).get("data", {})) is not None:
        installedby = install_info_data.get("installers", [])
        data["installers"] = installedby
        data["creator_id"] = install_info_data.get("creator", {})
        data["user"] = (await user_info_edge(installedby[0].get("id"))).get("data", {})
        if (appinfo := await app_info(id, data["user"].get("bot_id"))).get(
            "error"
        ) is None:
            data["app"] = appinfo.get("data", {})

    return data if data else {"error": "nonexistent"}


@app.get("/emoji/{name}")
async def emoji(name: str):
    return await emoji_info(name)


# @app.get("/promote/{id}")
# async def promote(id: str):
#     if not re.fullmatch(r"U[A-Z0-9]{6,}", id):
#         return {"error": "invalid user ID"}
#     return await promote_member(id)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", reload="--reload" in sys.argv)

# conversations.genericInfo
