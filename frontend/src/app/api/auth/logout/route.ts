import { NextResponse } from "next/server";
import { clearSessionCookies, getSessionTokens } from "@/lib/auth/session";

const BACKEND_URL = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";

export async function POST() {
  try {
    const { accessToken, refreshToken } = await getSessionTokens();
    if (accessToken) {
      await fetch(`${BACKEND_URL}/api/v1/auth/logout`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: refreshToken || "" }),
      }).catch(() => {});
    }

    const response = NextResponse.json({ success: true });
    clearSessionCookies(response.headers);
    return response;
  } catch {
    const response = NextResponse.json({ success: true });
    clearSessionCookies(response.headers);
    return response;
  }
}
