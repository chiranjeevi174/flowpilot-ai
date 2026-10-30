import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import httpx
from flowpilot.core.config import get_settings


async def check_test_recipients():
    settings = get_settings()
    token = settings.WHATSAPP_ACCESS_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    version = settings.WHATSAPP_GRAPH_API_VERSION

    headers = {"Authorization": f"Bearer {token}"}
    base = f"https://graph.facebook.com/{version}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Check phone number fields
        res = await client.get(
            f"{base}/{phone_id}",
            headers=headers,
            params={
                "fields": "id,display_phone_number,status,quality_rating,verified_name,throughput"
            },
        )
        print("Phone fields:", res.status_code, res.json())


if __name__ == "__main__":
    asyncio.run(check_test_recipients())
