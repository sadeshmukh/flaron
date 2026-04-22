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
BASE = _env("BASE_SLACK_API", "https://hackclub.enterprise.slack.com/api/")
ENTERPRISE_BASE = _env("ENTERPRISE_BASE", "https://hackclub.slack.com/")
EID = _env("EID", "E09V59WQY1E")
TID = _env("TID", "T0266FRGM")
USE_WEIRD_TEAM_ROUTE_THING = _env("UWTRT", "false").lower() == "true"

# region primitives


async def req(
    path: str, form: dict = {}, params: dict[str, str] = {}, use_enterprise_base=False
) -> dict:
    headers = {"Cookie": f"d={quote(XOXD)}", "Accept": "*/*"}
    params.update(
        {
            "slack_route": (
                f"{EID}:{EID}" if not USE_WEIRD_TEAM_ROUTE_THING else f"{EID}:{TID}"
            )
        }
    )
    url = (
        f"{BASE}{path}?{urlencode(params)}"
        if not use_enterprise_base
        else f"{ENTERPRISE_BASE}api/{path}?{urlencode(params)}"
    )
    logger.debug(f"requesting {url} with form {form}")
    form.update({"token": quote(XOXC)})
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url, data=form) as res:
            data = await res.json()
            if not data.get("ok"):
                logger.info(
                    f"error in {path}: {data.get('error', 'this should never be seen')}"
                )
                logger.info(f"form data was: {form}")
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
                logger.info(
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


async def fetch_commands(dump=False) -> dict:
    data = await req("client.appCommands")
    if err := data.get("error"):
        logger.error(f"app commands error: {err}")
        print(data)
        return {"error": "unknown"}
    if dump:
        json.dump(data, open("appcommands.json", "w"), indent=2)
    try:
        commands = data.get("commands", [])
        # things we care about{name, usage, desc, type: core/app, app_name, app (is id), icons}
        # name is e.g. /abcd
        return {
            "data": {
                cmd.get("name").strip("/"): {
                    "name": cmd.get("name"),
                    "usage": cmd.get("usage"),
                    "description": cmd.get("desc"),
                    "app_name": cmd.get("app_name"),
                    "app_id": cmd.get("app"),
                    "icons": cmd.get("icons", []),
                }
                for cmd in commands
                if cmd.get("type") == "app"
            }
        }

    except Exception as err:
        logger.error(f"app commands parsing error: {err}")
        return {"error": "unknown"}


async def who_installed_it(app_id: str) -> list:
    headers = {
        "Cookie": f"d={quote(XOXD)}",
        "Accept": "text/html",
    }
    url = f"{ENTERPRISE_BASE}marketplace/{app_id}"
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
                {
                    "id": auth.get("encodedUserLink"),
                    "name": auth.get("userDisplayName"),
                    "access": auth.get("fullDescription"),
                }
                for auth in authorizations
            ]


async def app_info(app_id: str, bot_id: str = "") -> dict:
    data = await req(
        "apps.profile.get",
        params={"app": app_id, "bot": bot_id} if bot_id else {"app": app_id},
    )
    if err := data.get("error"):
        logger.error(f"app info error: {err}")
        return {"error": "unknown"}
    try:

        profile = data.get("app_profile", {})
        # fields I'm going to show: id, name, desc, long_desc, date_installed, icons, bot_user: {id, username, memberships_count}
        # print(profile.keys())
        ret = {
            "app_id": profile.get("id"),
            "name": profile.get("name"),
            "tagline": profile.get("desc"),
            "description": profile.get("long_desc"),
            "date_installed": profile.get("date_installed"),  # unix timestamp
            "icons": profile.get("icons", {}),
        }
        if bot_id:
            ret["user_id"] = profile.get("bot_user", {}).get("id")
            ret["username"] = profile.get("bot_user", {}).get("username")
            ret["count_in"] = profile.get("bot_user", {}).get("memberships_count")
        return {"data": ret}

    except:
        logger.error(f"app info parsing error: {err}")
        return {"error": "unknown"}


async def user_info_edge(id: str) -> dict:
    data = await edge(
        "users/info",
        jsondata={
            "updated_ids": {id: 0},
        },
    )
    if err := data.get("error"):
        logger.error(f"user info edge error: {err}")
        return {"error": "unknown"}
    try:
        user = data.get("results", [])[0]
        # fields: id, name, deleted, real_name, tz/tz_label/tz_offset, profile (title, phone, skype???, real_name, display_name
        # ... other stuff is useless
        # api_app_id, bot_id, always_active
        # is_admin, is_owner, is_primary_owner, is_restricted, is_ultra_restricted
        # duped/useless data elsewhere, maybe include status? or not ig
        ret = {
            "id": user.get("id"),
            "name": user.get("name"),
            "real_name": user.get("real_name"),
            "deleted": user.get("deleted"),
            "tz": user.get("tz"),
            "tz_label": user.get("tz_label"),
            "tz_offset": user.get("tz_offset"),
            "title": user.get("profile", {}).get("title"),
            "phone": user.get("profile", {}).get("phone"),
            "display_name": user.get("profile", {}).get("display_name"),
            "is_admin": user.get("is_admin"),
            "is_owner": user.get("is_owner"),
            "is_primary_owner": user.get("is_primary_owner"),
            "is_restricted": user.get("is_restricted"),
            "is_ultra_restricted": user.get("is_ultra_restricted"),
        }
        if user.get("is_bot"):
            ret["is_bot"] = True
            ret["bot_id"] = user.get("profile", {}).get("bot_id")
            ret["app_id"] = user.get("profile", {}).get("api_app_id")
            ret["always_active"] = user.get("always_active")
        return {"data": ret}
    except Exception as err:
        logger.error(f"user info edge parsing error: {err}")
        return {"error": "unknown"}


async def promote_member(user_id: str) -> dict:
    # from mcg
    data = await req(
        "enterprise.users.admin.setRegular",
        form={
            "user": user_id,
            "scope_to": "team",
            "team": TID,
        },
        use_enterprise_base=True,
    )
    if err := data.get("error") or not data.get("ok"):
        logger.error(f"promoting error: {err}")
        return {"error": "unknown"}
    return {"data": "success"}


async def testty(app_id: str):
    headers = {
        "Cookie": f"d={quote(XOXD)}",
        "Accept": "text/html",
    }
    url = f"https://hackclub.slack.com/marketplace/{app_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as res:
            html = await res.text()

            matches = re.finditer(
                r'data-automount-component="([^"]+)"\s+data-automount-props="([^"]+)"',
                html,
            )
        result: dict[str, list] = {}
        for match in matches:
            component = match.group(1)
            props = json.loads(match.group(2).replace("&quot;", '"'))
            result.setdefault(component, []).append(props)
        json.dump(result, open("automount.json", "w"), indent=2)


if __name__ == "__main__":
    import asyncio

    asyncio.run(who_installed_it("A0ADCQX31B2"))
