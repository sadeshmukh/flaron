import re
import aiohttp
import asyncio

from contextlib import asynccontextmanager
from fastapi import FastAPI, Header
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import sys
import os
import logging
from dotenv import load_dotenv

load_dotenv()


from private import cid_by_name_private, cname_private
from utils import _env
from cache import (
    init_cache,
    get_all_cached_name_to_id,
    search_cached_channels,
    invalidate_channel,
    purge_channel_cache,
    mark_channel_failed,
    unmark_channel_failed,
    is_channel_failed,
    failed_channels_sync_loop,
    cache_channels,
)
from userbot import (
    emoji_info,
    fetch_commands,
    channel_counts,
    channel_info,
    channel_managers,
    bulk_cname_to_cid,
    promote_member,
    user_info_edge,
    install_info,
    app_info,
    _resolve_channel_names,
)

logging.basicConfig(level=logging.INFO, format="FLARON [%(name)s]: %(message)s")
logger = logging.getLogger("main")

commands: dict = {}
startup_stale: list = []


async def _re_resolve_startup_cache():
    global startup_stale
    snapshot = get_all_cached_name_to_id()
    if not snapshot:
        return
    purge_channel_cache()
    fresh = await _resolve_channel_names(list(snapshot.keys()))
    cache_channels(
        {v["id"]: {"name": k, "private": v["private"]} for k, v in fresh.items()}
    )
    for name, cached_data in snapshot.items():
        cached_id = cached_data["id"]
        fresh_id = fresh[name]["id"] if name in fresh else None
        if fresh_id != cached_id:
            unmark_channel_failed(cached_id)
            startup_stale.append(
                {"name": name, "stale_id": cached_id, "fresh_id": fresh_id}
            )
    if startup_stale:
        logger.info(f"{len(startup_stale)} stale channel mappings found on startup")


@asynccontextmanager
async def lifespan(app: FastAPI):

    global commands
    init_cache()
    await _re_resolve_startup_cache()
    if (data := await fetch_commands()).get("error"):
        logger.error(f"app commands error: {data.get('error')}")
        exit(1)
    commands = data.get("data", {})
    if not commands:
        logger.warning("commands not found, oop")
        exit(1)
    sync_task = asyncio.create_task(failed_channels_sync_loop())
    yield
    sync_task.cancel()


# struct: {command name -> {name, usage, description, app_name, app_id,
# icons: {image_32, image_48, image_64, image_72}}}
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# @app.get("/")
# async def root():
#     return FileResponse(
#         path=os.path.join(os.path.dirname(__file__), "client.html"),
#         media_type="text/html",
#     )


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

    if is_channel_failed(id):
        ret["error"] = "nonexistent"
        return ret

    if (
        "error" in (managers := await channel_managers(id))
        and managers["error"] == "nonexistent"
    ):
        mark_channel_failed(id)
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
    result = await bulk_cname_to_cid([name])
    if entry := result.get(name):
        return await channel(entry["id"])
    id = (await cid_by_name_private(name)).get("id", "")
    if not id:
        return {"error": "nonexistent"}
    return await channel(id)


@app.post("/cnames")
async def channels_by_name(
    names: list[str], x_admin_key: str | None = Header(default=None)
):
    bypass = x_admin_key is not None and x_admin_key == _env("ADMIN_KEY", "")
    if bypass:
        logger.info(f"BYPASS {names}")
    return await bulk_cname_to_cid(names, bypass_cache=bypass)


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


@app.get("/admin/search")
async def search_cache(q: str, x_admin_key: str | None = Header(default=None)):
    if not x_admin_key or x_admin_key != _env("ADMIN_KEY", ""):
        return {"error": "unauthorized"}
    matches = search_cached_channels(q)
    return {"query": q, "count": len(matches), "results": matches}


@app.post("/admin/revalidate")
async def revalidate_channels(x_admin_key: str | None = Header(default=None)):
    if not x_admin_key or x_admin_key != _env("ADMIN_KEY", ""):
        return {"error": "unauthorized"}
    snapshot = get_all_cached_name_to_id()
    if not snapshot:
        return {"removed": []}
    purge_channel_cache()
    fresh = await _resolve_channel_names(list(snapshot.keys()))
    cache_channels(
        {v["id"]: {"name": k, "private": v["private"]} for k, v in fresh.items()}
    )
    removed = []
    for name, cached_data in snapshot.items():
        cached_id = cached_data["id"]
        fresh_id = fresh[name]["id"] if name in fresh else None
        if fresh_id != cached_id:
            unmark_channel_failed(cached_id)
            removed.append({"name": name, "stale_id": cached_id, "fresh_id": fresh_id})
    return {"removed": removed}


@app.get("/admin/stale")
async def get_startup_stale(x_admin_key: str | None = Header(default=None)):
    if not x_admin_key or x_admin_key != _env("ADMIN_KEY", ""):
        return {"error": "unauthorized"}
    return {"count": len(startup_stale), "stale": startup_stale}


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
