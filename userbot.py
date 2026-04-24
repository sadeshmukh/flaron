import json
import re
import sys
import aiohttp
import logging
from utils import _env
from urllib.parse import quote, urlencode
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TaskProgressColumn,
    TextColumn,
)


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
    path: str,
    form: dict = {},
    params: dict[str, str] = {},
    use_enterprise_base=False,
    override_XOXC=None,
    override_XOXD=None,
) -> dict:
    headers = {"Cookie": f"d={quote(override_XOXD or XOXD)}", "Accept": "*/*"}
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
    form.update({"token": quote(override_XOXC or XOXC)})
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


async def emoji_info(name: str) -> dict:
    data = await req(
        "emoji.adminList",
        form={"page": 1, "count": 100, "queries": json.dumps([name]), "user_ids": "[]"},
        override_XOXC=_env("XOXC_PROMOTE", XOXC),
        override_XOXD=_env("XOXD_PROMOTE", XOXD),
    )
    if err := data.get("error", ""):
        logger.error(f"emoji info error: {err}")
        return {"error": "unknown"}
    try:
        emojis = [e for e in data.get("emoji", []) if e.get("name") == name]
        if not emojis or emojis[0].get("name") != name:
            return {"error": "not found"}
        emoji = emojis[0]
        return {
            "data": {
                "url": emoji.get("url"),
                "is_alias": emoji.get("is_alias"),
                "canonical": emoji.get("alias_for", ""),
                "user_id": emoji.get("user_id"),
                "user_display": emoji.get("user_display_name"),
                "synonyms": emoji.get("synonyms", []),
            }
        }
    except Exception as err:
        logger.error(f"emoji info parsing error: {err}")
        return {"error": "unknown"}


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
    DO_NOT_PROMOTE = ["U07CAPBB9B5", "U07NKS9S8GZ"]
    if user_id in DO_NOT_PROMOTE:
        logger.warning(
            f"skipping promotion of {user_id} since they're on the do not promote list"
        )
        return {"error": "do not promote"}
    data = await req(
        "users.admin.setRegular",  # enterprise.?
        form={
            "user": user_id,
            "scope_to": "team",
            "team": TID,
        },
        use_enterprise_base=True,
        override_XOXC=_env("XOXC_PROMOTE", XOXC),
        override_XOXD=_env("XOXD_PROMOTE", XOXD),
    )
    if err := data.get("error") or not data.get("ok"):
        if err == "no_perms":
            logger.debug("already promoted")
            return {"error": "already promoted"}
        logger.error(f"promoting error: {err}")
        return {"error": "unknown"}
    return {"data": "success"}


# region local only


async def list_mcgs():
    import asyncio

    mcgs = []
    cursor_mark = None
    retry_count = 0
    max_retries = 3

    try:
        with open("mcgs.json", "r") as f:
            cache = json.load(f)
            if isinstance(cache, dict) and "mcgs" in cache:
                mcgs = cache["mcgs"]
                cursor_mark = cache.get("cursor_mark")
                logger.info(
                    f"Resuming from cursor: {cursor_mark}, already fetched {len(mcgs)} users"
                )
            elif isinstance(cache, list):
                pass
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    total_mcgs = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("│ {task.completed}/{task.total} users"),
    ) as progress:
        task = progress.add_task("Fetching MCGs...", total=None)

        while True:
            form = {
                "count": 1000,
                "include_bots": 0,
                "exclude_slackbot": 1,
                "include_deleted": 0,
                "sort_dir": "asc",
                "sort": "real_name",
                "target_team": TID,
                "query": '{"type":"and","clauses":[{"type":"is","value":"user"},{"type":"and","clauses":[{"type":"or","clauses":[{"type":"level","value":"restricted"}]}]}]}',
            }
            if cursor_mark:
                form["cursor_mark"] = cursor_mark

            try:
                data = await asyncio.wait_for(
                    req("users.admin.fetchTeamUsers", form=form), timeout=30
                )
                retry_count = 0

                if err := data.get("error") or not data.get("ok"):
                    logger.error(f"API error: {err}")
                    raise Exception(f"API error: {err}")

                page_users = [
                    {
                        "id": i.get("id"),
                        "updated": i.get("updated"),
                        "created": i.get("created"),
                    }
                    for i in data.get("items", [])
                ]

                mcgs.extend(page_users)
                cursor_display = (cursor_mark or "start")[:8]
                next_cursor = data.get("next_cursor_mark")

                if total_mcgs is None:
                    total_mcgs = data.get("num_found", len(mcgs))

                checkpoint = {
                    "mcgs": mcgs,
                    "cursor_mark": next_cursor,
                    "total_fetched": len(mcgs),
                }
                with open("mcgs.json", "w") as f:
                    json.dump(checkpoint, f, indent=2)

                progress.update(
                    task,
                    advance=len(page_users),
                    total=total_mcgs,
                    description=f"Fetching MCGs... (cursor: {cursor_display})",
                )

                if not next_cursor or next_cursor == cursor_mark:
                    break
                cursor_mark = next_cursor

            except asyncio.TimeoutError:
                retry_count += 1
                logger.warning(
                    f"Request timeout (attempt {retry_count}/{max_retries}), retrying..."
                )
                if retry_count > max_retries:
                    logger.error("Max retries exceeded on timeout")
                    raise Exception(
                        f"Max retries exceeded on timeout at {len(mcgs)} users"
                    )
                await asyncio.sleep(2**retry_count)

            except Exception as err:
                logger.error(f"Error fetching MCGs: {err}")
                raise Exception(f"Failed after {len(mcgs)} users: {err}")

        progress.update(
            task,
            total=len(mcgs),
            completed=len(mcgs),
            description=f"Done — {len(mcgs)} MCGs fetched",
        )

    json.dump(mcgs, open("mcgs.json", "w"), indent=2)


async def promote_em_all():
    import asyncio

    with open("mcgs.json", "r") as f:
        data = json.load(f)
        mcgs = data if isinstance(data, list) else data.get("mcgs", [])

    mcgs_sorted = sorted(mcgs, key=lambda x: x.get("updated", 0), reverse=True)

    stats = {
        "success": 0,
        "already_promoted": 0,
        "failed": 0,
        "skipped": 0,
        "rate_limited": 0,
    }
    error_breakdown = {}
    promoted_ids = set()
    retry_queue = {}

    resume_file = "promote_state.json"
    try:
        with open(resume_file, "r") as f:
            state = json.load(f)
            promoted_ids = set(state.get("promoted_ids", []))
            stats = state.get("stats", stats)
            error_breakdown = state.get("error_breakdown", {})
            retry_queue = state.get("retry_queue", {})
            logger.info(
                f"Resuming: {len(promoted_ids)} already processed, {len(retry_queue)} in retry queue"
            )
    except FileNotFoundError:
        pass

    batch_size = 50
    min_batch_size = 3
    max_batch_size = 100
    batch_delay = 0.5
    max_retries = 3

    def save_checkpoint():
        with open(resume_file, "w") as f:
            json.dump(
                {
                    "promoted_ids": list(promoted_ids),
                    "stats": stats,
                    "error_breakdown": error_breakdown,
                    "retry_queue": retry_queue,
                },
                f,
                indent=2,
            )

    async def promote_batch(batch, semaphore):
        """Promote a batch in parallel with semaphore control."""
        nonlocal batch_size, batch_delay
        rate_limited_users = []

        async def promote_with_semaphore(user):
            async with semaphore:
                if user["id"] in promoted_ids:
                    stats["skipped"] += 1
                    return user["id"], "skipped", False

                result = await promote_member(user["id"])

                if result.get("data") == "success":
                    promoted_ids.add(user["id"])
                    stats["success"] += 1
                    return user["id"], "success", False
                elif result.get("error") == "already promoted":
                    promoted_ids.add(user["id"])
                    stats["already_promoted"] += 1
                    return user["id"], "already_promoted", False
                elif result.get("error") == "rate_limited":
                    stats["rate_limited"] += 1
                    return user["id"], "rate_limited", True
                else:
                    error_msg = result.get("error", "unknown")
                    error_breakdown[error_msg] = error_breakdown.get(error_msg, 0) + 1
                    stats["failed"] += 1
                    return (
                        user["id"],
                        f"failed: {error_msg}",
                        False,
                    )

        results = await asyncio.gather(
            *[promote_with_semaphore(user) for user in batch],
            return_exceptions=True,
        )

        for r in results:
            if isinstance(r, tuple) and len(r) == 3:
                user_id, status, is_rate_limited = r
                if is_rate_limited:
                    rate_limited_users.append(user_id)

        error_count = sum(
            1
            for r in results
            if isinstance(r, Exception)
            or ("failed" in str(r) and "rate_limited" not in str(r))
        )
        if error_count > batch_size * 0.3:
            batch_size = max(min_batch_size, int(batch_size * 0.7))
            batch_delay = min(4.0, batch_delay * 1.5)
            logger.warning(
                f"High error rate, reducing batch size to {batch_size}, delay to {batch_delay}s"
            )
        elif error_count == 0 and batch_size < max_batch_size:
            batch_size = min(max_batch_size, int(batch_size * 1.1))
            batch_delay = max(0.2, batch_delay * 0.9)

        return rate_limited_users

    total = len(mcgs_sorted)
    remaining = [m for m in mcgs_sorted if m["id"] not in promoted_ids]

    import time

    batch_times = []

    def format_eta(seconds):
        """Format seconds to human readable time."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        else:
            return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("│"),
        TextColumn("[green]{task.fields[success]}✓[/green]"),
        TextColumn("[yellow]{task.fields[already]}~[/yellow]"),
        TextColumn("[cyan]{task.fields[ratelimit]}⚡[/cyan]"),
        TextColumn("[red]{task.fields[failed]}✗[/red]"),
        TextColumn("[dim]{task.fields[eta]}[/dim]"),
    ) as progress:
        task = progress.add_task(
            "Promoting MCGs...",
            total=total,
            success=stats["success"],
            already=stats["already_promoted"],
            ratelimit=stats["rate_limited"],
            failed=stats["failed"],
            eta="",
        )

        semaphore = asyncio.Semaphore(batch_size)
        run_start = time.time()
        items_at_start = stats["success"] + stats["already_promoted"] + stats["failed"]

        i = 0
        batch_num = 0
        while i < len(remaining):
            batch_start = time.time()
            batch = remaining[i : i + batch_size]
            batch_num += 1
            total_batches = -(-len(remaining) // batch_size)  # ceiling div (approx)

            items_done = stats["success"] + stats["already_promoted"] + stats["failed"]
            elapsed = time.time() - run_start
            new_items = items_done - items_at_start
            eta_text = ""
            if new_items > 0 and elapsed > 0:
                rate = new_items / elapsed
                remaining_items = total - items_done
                eta_text = format_eta(remaining_items / rate)

            progress.update(
                task,
                completed=items_done,
                description=f"Batch {batch_num}/{total_batches}",
                success=stats["success"],
                already=stats["already_promoted"],
                ratelimit=stats["rate_limited"],
                failed=stats["failed"],
                eta=f"ETA {eta_text}" if eta_text else "",
            )

            rate_limited_users = await promote_batch(batch, semaphore)

            batch_times.append(time.time() - batch_start)
            if len(batch_times) > 10:
                batch_times.pop(0)

            for user_id in rate_limited_users:
                retry_queue[user_id] = retry_queue.get(user_id, 0) + 1

            save_checkpoint()

            if i + batch_size < len(remaining):
                await asyncio.sleep(batch_delay)

            i += batch_size

        retry_count = 0
        while retry_queue and retry_count < max_retries:
            retry_count += 1
            retry_users = []
            for user_id, attempts in list(retry_queue.items()):
                if attempts <= max_retries:
                    user = next((m for m in mcgs_sorted if m["id"] == user_id), None)
                    if user:
                        retry_users.append(user)

            if not retry_users:
                break

            wait_time = 2**retry_count
            progress.update(
                task,
                description=f"Rate limit retry {retry_count}/{max_retries}... waiting {wait_time}s",
                success=stats["success"],
                already=stats["already_promoted"],
                ratelimit=stats["rate_limited"],
                failed=stats["failed"],
                eta="",
            )
            await asyncio.sleep(wait_time)

            rate_limited_users = await promote_batch(retry_users, semaphore)
            for user_id in rate_limited_users:
                retry_queue[user_id] = retry_queue.get(user_id, 0) + 1
            for user_id in [u["id"] for u in retry_users]:
                if user_id not in rate_limited_users and user_id in retry_queue:
                    del retry_queue[user_id]

            save_checkpoint()

        progress.update(
            task,
            completed=total,
            description=f"Done! {stats['success']} promoted, {stats['already_promoted']} already promoted, {stats['rate_limited']} rate limited, {stats['failed']} failed",
            success=stats["success"],
            already=stats["already_promoted"],
            ratelimit=stats["rate_limited"],
            failed=stats["failed"],
            eta="",
        )

    logger.info(f"Final stats: {stats}")
    if error_breakdown:
        logger.info(f"Error breakdown: {error_breakdown}")
    logger.info(
        f"Failed retries (limit exceeded): {len([u for u, c in retry_queue.items() if c > max_retries])}"
    )
    save_checkpoint()


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

    # asyncio.run(list_mcgs())
    print(asyncio.run(emoji_info("sparkling_fart")))


# endregion
