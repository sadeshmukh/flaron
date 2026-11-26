import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

with patch.dict(
    os.environ,
    {
        "XOXC": "test-token",
        "XOXD": "test-cookie",
        "DS": "test-session",
        "UPSTASH_REDIS_REST_URL": "https://example.invalid",
        "UPSTASH_REDIS_REST_TOKEN": "test-redis-token",
    },
):
    import cache
    import userbot


class ChannelResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_privacy_reaches_cache_independently_of_token_suffix(self):
        formatted = "<#CPUBLIC> <#CPRIVATE> <#CJOINED|joined> <#CPUBLIC|alias>"
        with (
            patch.object(userbot, "_cname_queue", None),
            patch.object(userbot, "req", new_callable=AsyncMock) as req,
            patch.object(userbot, "edge", new_callable=AsyncMock) as edge,
            patch.object(cache, "redis", MagicMock()),
            patch.object(cache, "_channels", {}),
            patch.object(cache, "_name_to_id", {}),
        ):
            req.return_value = {
                "message": {"blocks": [{"text": {"text": formatted}}]}
            }
            edge.return_value = {
                "results": [
                    {"id": "CPUBLIC", "is_private": False},
                    {"id": "CJOINED", "is_private": True},
                ],
                "failed_ids": ["CPRIVATE"],
            }
            result = await userbot.bulk_cname_to_cid(
                ["PUBLIC", "private", "joined", "alias"], bypass_cache=True
            )
            self.assertEqual(
                result,
                {
                    "data": {
                        "public": {"id": "CPUBLIC", "private": False},
                        "private": {"id": "CPRIVATE", "private": True},
                        "joined": {"id": "CJOINED", "private": True},
                        "alias": {"id": "CPUBLIC", "private": False},
                    }
                },
            )
            self.assertFalse(cache.get_all_records()["CPUBLIC"]["private"])
            self.assertTrue(cache.get_cached_channel_id("private")["private"])
            self.assertEqual(
                edge.call_args.args,
                ("channels/info", {"ids": ["CPUBLIC", "CPRIVATE", "CJOINED"]}),
            )

    async def test_lookup_failures_do_not_overwrite_cache(self):
        for response in ({"error": "ratelimited"}, {"results": []}):
            with (
                self.subTest(response=response),
                patch.object(userbot, "req", new_callable=AsyncMock) as req,
                patch.object(userbot, "edge", new_callable=AsyncMock) as edge,
                patch.object(cache, "cache_channels") as persist,
            ):
                req.return_value = {
                    "message": {"blocks": [{"text": {"text": "<#CPUBLIC>"}}]}
                }
                edge.return_value = response
                with self.assertRaises(RuntimeError):
                    await userbot._bulk_cname_inner(["public"], bypass_cache=True)
                persist.assert_not_called()

    async def test_unresolved_names_are_not_classified(self):
        with (
            patch.object(userbot, "req", new_callable=AsyncMock) as req,
            patch.object(userbot, "edge", new_callable=AsyncMock) as edge,
        ):
            req.return_value = {
                "message": {"blocks": [{"text": {"text": "#missing"}}]}
            }
            self.assertEqual(await userbot._resolve_channel_names(["missing"]), {})
            edge.assert_not_called()

    async def test_batches_respect_full_serialized_body_budget(self):
        ids = [f"C{i:010d}" for i in range(1201)]
        for token in ("t" * 113, "t" * 1500):
            batches = []

            async def edge_info(path, jsondata):
                self.assertEqual(path, "channels/info")
                batch = jsondata["ids"]
                batches.append(batch)
                # Same wire format as edge(), including both token fields.
                body = json.dumps(
                    {
                        **jsondata,
                        "as_admin": True,
                        "token": token,
                        "enterprise_token": token,
                    },
                    separators=(",", ":"),
                ).encode()
                self.assertLessEqual(len(body), 9500)
                self.assertLessEqual(len(batch), 600)
                return {
                    "results": [{"id": cid, "is_private": False} for cid in batch]
                }

            with (
                self.subTest(token_length=len(token)),
                patch.object(userbot, "XOXC", token),
                patch.object(userbot, "edge", side_effect=edge_info),
            ):
                result = await userbot._channel_privacy(ids + ids[:20])
                self.assertEqual(result, dict.fromkeys(ids, False))
                self.assertEqual([cid for batch in batches for cid in batch], ids)
                self.assertGreater(len(batches), 1)


class CookieTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_dbd_on_both_request_paths(self):
        for dbd in ("", "device-binding-cookie"):
            with (
                self.subTest(dbd=dbd),
                patch.dict(os.environ, {"DBD": dbd, "DS": "session"}),
                patch.object(userbot, "XOXD", "cookie+value"),
                patch.object(userbot.aiohttp, "ClientSession") as session_factory,
            ):
                session = session_factory.return_value.__aenter__.return_value
                session.post = MagicMock()
                session.post.return_value.__aenter__.return_value.json = AsyncMock(
                    return_value={"ok": True}
                )
                suffix = f"; dbd={dbd}" if dbd else ""
                await userbot.req("auth.test", form={}, params={})
                self.assertEqual(
                    session_factory.call_args.kwargs["headers"]["Cookie"],
                    "d=cookie%2Bvalue" + suffix,
                )
                await userbot.edge("channels/info", {"ids": []}, params={})
                self.assertEqual(
                    session_factory.call_args.kwargs["headers"]["Cookie"],
                    "d=cookie%2Bvalue; d-s=session; ic=session" + suffix,
                )


if __name__ == "__main__":
    unittest.main()
