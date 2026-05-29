# Flaron

Flaron is an API to get all the Slack data you ever wish you had, built on top of userbotted, official, and scraped webpages. It additionally aggregates additional external APIs. View the full API reference [here](https://flaron.halceon.dev/docs) Here's some of the stuff available through Flaron:

- User info: Slack profile data, IDV status, Joe status
  - TBD: extras
- Channel info: member count (including individual member/bot counts), managers, creator, previous names, and more
  - much of this info is neither available through the UI or via the official API!
- App info: installers, creator, channel count (/flaron app @bot)
  - this information is also not available through the UI or official API
- Emoji info: creator, synonyms
- Search: channels and users
  - currently used in many of my personal (private) projects related to HC for easy & lightweight search
- Private channels: retrieve from the DB, quickly look up any name, or look up thousands of names in bulk.
- ...and more!

Access to Flaron is controlled via a bot and API. In Slack, use the message shortcut "Flaron -> Reveal Channels" to get a list of all channels mentioned within a message. If you're using rope (#rope), it is one of the endpoints available as your private channel DB. Use /flaron for much info within Slack.

Note that the UI is highly AI assisted, as it is not the main focus of this project, and is meant to be a simplistic demo client for the APIs available here. That being said, it provides a good example of how to use the APIs, e.g. search-as-you-type user/channel search, and the ability to quickly query the private channel DB both in bulk and individually.

# How?

Most data from Slack comes from userbotted endpoints. These come in two varieties - flannel requests and normal requests. Flannel is Slack's edge API and contains much of the random info you see that loads everywhere throughout Slack. Normal requests are made more "intentionally", whatever you want to call it, and oftentimes have worse ratelimits. Every single piece of information that you ever see on Slack is available through one of these two methods, which makes Flaron easily extensible.

Private channel data is stored in a Redis instance, which is updated through some userbotted endpoints and is stored in Upstash.

If you have any questions about how this was implemented, or how to obtain any information here, feel free to ask!

# Env vars

You can identify missing environment variables, as any code path that uses it should error upon its absence. Here are the absolute necessities, but there may be many I haven't documented here:

XOXC, XOXD, XOXC_PROMOTE, XOXD_PROMOTE: scraped tokens for the account you wish to impersonate, and its higher scoped variant for calls not accessible elsewhere. Some endpoints that require PROMOTE tokens may not be accessible to regular workspace members.

DS: needed occasionally for PROMOTE actions

XOXP, XOXB, XAPP: tokens for the bot user, for the bot client

BASE_CMD: starting slash command for the bot (must also be in your manifest)

UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN: I use upstash to store the private channel DB

You may ask what PROMOTE is - these are actions available on the admin dashboard (regardless of whether they're actually admin features) and thus have different access. If your normal XOXC/XOXD tokens work, great! Otherwise, this may be a good shot to try and fix it.

## Other workspaces

You may find yourself wanting to run Flaron on a non-HC workspace. There are a few more variables to consider in that case:

EID, TID: enterprise and team ID

ENTERPRISE_BASE, BASE_SLACK_API: self explanatory

UWTRT: set this to true if you're not using an enterprise, but note that stuff might be slightly different, and it's not been tested without enterprise.

---

If you ever use Flaron in a personal project, please let me know! I would love to see what you make. If you have any questions or suggestions, DM me @sahil on Slack & talk to me before opening any issues or PRs.
