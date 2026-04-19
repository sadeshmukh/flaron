import json
import re
import aiohttp
import logging
from utils import _env
from urllib.parse import quote, urlencode


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()


logger = logging.getLogger(__name__)

XOXC = _env("XOXC")
XOXD = _env("XOXD")
BASE = "https://hackclub.enterprise.slack.com/api/"
EID = "E09V59WQY1E"
# TID = "T0266FRGM"

# region primitives


async def req(path: str, form: dict = {}, params: dict[str, str] = {}) -> dict:
    headers = {"Cookie": f"d={quote(XOXD)}", "Accept": "*/*"}
    params.update({"slack_route": f"{EID}:{EID}"})
    url = f"{BASE}{path}?{urlencode(params)}"
    logging.info(url)
    form.update({"token": quote(XOXC)})
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url, data=form) as res:
            data = await res.json()
            if not data.get("ok"):
                logging.info(
                    f"error in {path}: {data.get('error', 'this should never be seen')}"
                )
                return {"error": data.get("error")}

            return data


async def edge(path: str, jsondata: dict = {}, params: dict[str, str] = {}) -> dict:
    headers = {
        "Accept": "*/*",
        "Cookie": f"d={quote(XOXD)}; d-s={_env('DS')}; ic={_env('DS')}",
    }
    url = f"https://edgeapi.slack.com/cache/{EID}/{path}"

    jsondata.update({"as_admin": True, "token": XOXC, "enterprise_token": XOXC})
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(
            url, data=json.dumps(jsondata, separators=(",", ":"))
        ) as res:
            data = await res.json()
            if not data.get("ok"):
                logging.info(
                    f"error in {path}: {data.get('error', 'this should never be seen')}"
                )
                return {"error": data.get("error")}

            return data


# endregion primitives


async def channel_managers(channel_id: str) -> dict:
    data = await req(
        "admin.roles.entity.listAssignments", form={"entity_id": channel_id}
    )
    if err := data.get("error", ""):
        pretty = (
            "private"
            if err == "no_perms"
            else "nonexistent" if err == "invalid_entity_id" else "unknown"
        )
        if pretty == "unknown":
            logger.error(f"what in the world is this error in {channel_id}: {err}")
        return {"error": pretty}
    try:
        return {"data": data.get("role_assignments", [])[0].get("users", [])}
    except Exception:
        logger.debug(f"Failed to get managers for {channel_id}")
        return {"data": []}


async def channel_counts(channel_id: str) -> dict:
    data = await edge("users/counts", jsondata={"channel": channel_id})
    # lots of extraneous, just show: total, bots
    if err := data.get("error", ""):
        logger.error(f"channel counts error: {err}")
        return {"error": "unknown or private"}
    try:
        return {
            "data": {
                "total": data.get("counts", {}).get("people"),
                "bots": data.get("counts", {}).get("bots"),
            }
        }
    except Exception as err:
        logger.error(f"channel count parsing broke: {err}")
        return {"error": "unknown"}


async def channel_info(channel_id: str) -> dict:
    data = await edge(
        "channels/info", {"check_membership": True, "updated_ids": {channel_id: 0}}
    )
    if err := data.get("error"):
        logger.error(f"channel info error: {err}")
        return {"error": err}
    try:
        channel = data.get("results", [])[0]
        # creator, name, previous_names, created, is_archived
        # purpose.value, topic.value
        # properties - tbd, but has: tabz, tabs (which look identical?)

        return {
            "data": {
                "creator": channel["creator"],
                "name": channel["name"],
                "previous_names": channel["previous_names"],
                "created": channel["created"],
                "is_archived": channel["is_archived"],
                "description": channel["purpose"]["value"],
                "topic": channel["topic"]["value"],
            }
        }
    except Exception as err:
        logger.error(f"channel info error: {err}")
        return {"error": "unknown"}


async def get_plausible_names(channel_id: str) -> dict:
    data = await req(
        "search.modules.messages",
        form={
            "query": channel_id,
            "search_tab_filter": "messages",
            "module": "messages",
            # "page": 1,
            # "count": 20,
        },
    )
    if err := data.get("error"):
        logger.error(f"plausible names error: {err}")
        return {"error": "unknown"}
    try:
        # print(json.dumps(data.get("items")))
        msgs = [
            item.get("messages", [])[0].get("text") for item in data.get("items", [])
        ]
        print(msgs)
        return {}

    except Exception as err:
        logger.error(f"plausible names parsing error: {err}")
        return {"error": "unknown"}


async def name_to_id(name: str) -> dict:
    data = await edge(
        "channels/search",
        jsondata={
            "query": name,
            # "check_membership": False,
            "count": 1,
            # "default_workspace": TID,
            # "filter": "xws",
            # "include_record_channels": True,
            # "top_channels": [],
            # "fuzz": 1,
        },
    )
    if err := data.get("error"):
        logger.error(f"channel info error: {err}")
        return {"error": err}
    try:
        if data.get("results", [])[0].get("name") != name:
            return {"error": "not found"}
        return {"data": {"id": data.get("results", [])[0].get("id")}}
    except Exception:
        logger.error(f"channel search (name to id) error: {err}")
        return {"error": "unknown"}


async def user_info(user_id: str) -> dict:
    data = await req("users.profile.get", params={"user": user_id})
    # {profile: {title, real_name, display_name}}
    # there are other fields, but without associated data, prob an extras req
    return data


async def userboot():
    data = await req("client.userBoot")
    if err := data.get("error"):
        logger.error(f"userboot error: {err}")
        print(data)
        return {"error": "unknown"}
    json.dump(data, open("userboot.json", "w"), indent=2)
    return data


async def appcommands():
    data = await req("client.appCommands")
    if err := data.get("error"):
        logger.error(f"app commands error: {err}")
        print(data)
        return {"error": "unknown"}
    json.dump(data, open("appcommands.json", "w"), indent=2)
    return data


async def who_installed_it(app_id: str) -> list:
    headers = {
        "Cookie": f"d={quote(XOXD)}",
        "Accept": "text/html",
    }
    url = f"https://hackclub.slack.com/marketplace/{app_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as res:
            html = await res.text()

            match = re.search(
                r'data-automount-component="AppDirectoryAuthorizations"\s+data-automount-props="([^"]+)"',
                html,
            )
            if not match:
                return []
            props = json.loads(match.group(1).replace("&quot;", '"'))
            authorizations = props.get("authorizations", [])
            return [
                {"id": auth.get("encodedUserLink"), "name": auth.get("userDisplayName")}
                for auth in authorizations
            ]


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(who_installed_it("A0ADCQX31B2")))
