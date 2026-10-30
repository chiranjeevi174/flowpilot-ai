import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import httpx
from flowpilot.core.config import get_settings


async def check_waba_subscription():
    settings = get_settings()
    token = settings.WHATSAPP_ACCESS_TOKEN
    waba_id = settings.WHATSAPP_BUSINESS_ACCOUNT_ID
    version = settings.WHATSAPP_GRAPH_API_VERSION

    headers = {"Authorization": f"Bearer {token}"}
    base = f"https://graph.facebook.com/{version}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Check current subscribed apps
        res = await client.get(f"{base}/{waba_id}/subscribed_apps", headers=headers)
        print("Current subscribed apps:", res.status_code, res.json())

        # Test subscribing our app to this WABA
        res_post = await client.post(f"{base}/{waba_id}/subscribed_apps", headers=headers)
        print("POST subscribed_apps result:", res_post.status_code, res_post.json())

        # Check subscribed apps again
        res2 = await client.get(f"{base}/{waba_id}/subscribed_apps", headers=headers)
        print("Subscribed apps after POST:", res2.status_code, res2.json())


if __name__ == "__main__":
    asyncio.run(check_waba_subscription())
