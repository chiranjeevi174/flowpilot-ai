import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import httpx
from flowpilot.core.config import get_settings


async def inspect_meta():
    settings = get_settings()
    token = settings.WHATSAPP_ACCESS_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    waba_id = settings.WHATSAPP_BUSINESS_ACCOUNT_ID
    app_id = settings.WHATSAPP_APP_ID
    app_secret = settings.WHATSAPP_APP_SECRET
    version = settings.WHATSAPP_GRAPH_API_VERSION

    headers = {"Authorization": f"Bearer {token}"}
    base = f"https://graph.facebook.com/{version}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # App subscriptions query requires app access token: app_id|app_secret
        if app_id and app_secret:
            app_token = f"{app_id}|{app_secret}"
            print(f"\n=== Inspecting App Subscriptions for App {app_id} ===")
            res_sub = await client.get(
                f"{base}/{app_id}/subscriptions", headers={"Authorization": f"Bearer {app_token}"}
            )
            print("App subscriptions status:", res_sub.status_code)
            print("App subscriptions response:", res_sub.json())


if __name__ == "__main__":
    asyncio.run(inspect_meta())
