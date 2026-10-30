import { NextResponse } from "next/server";
import {
  clearSessionCookies,
  getSessionTokens,
  refreshAccessToken,
  setSessionCookies,
} from "@/lib/auth/session";

const BACKEND_URL = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";

export async function GET() {
  try {
    const tokens = await getSessionTokens();
    let accessToken = tokens.accessToken;
    const refreshToken = tokens.refreshToken;

    if (!accessToken && !refreshToken) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    let refreshedTokens: { accessToken: string; refreshToken?: string; expiresIn: number } | null =
      null;

    // If access token is missing, attempt refresh
    if (!accessToken && refreshToken) {
      refreshedTokens = await refreshAccessToken(refreshToken);
      if (refreshedTokens) {
        accessToken = refreshedTokens.accessToken;
      } else {
        const res = NextResponse.json({ error: "Session expired" }, { status: 401 });
        clearSessionCookies(res.headers);
        return res;
      }
    }

    let userRes = await fetch(`${BACKEND_URL}/api/v1/users/me`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    });

    // If access token expired, try refreshing once
    if (userRes.status === 401 && refreshToken) {
      refreshedTokens = await refreshAccessToken(refreshToken);
      if (refreshedTokens) {
        accessToken = refreshedTokens.accessToken;
        userRes = await fetch(`${BACKEND_URL}/api/v1/users/me`, {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        });
      }
    }

    if (!userRes.ok) {
      const res = NextResponse.json({ error: "Unauthorized" }, { status: 401 });
      clearSessionCookies(res.headers);
      return res;
    }

    const userData = await userRes.json();
    const response = NextResponse.json({ user: userData });

    if (refreshedTokens) {
      setSessionCookies(
        response.headers,
        refreshedTokens.accessToken,
        refreshedTokens.refreshToken,
        refreshedTokens.expiresIn
      );
    }

    return response;
  } catch (error: any) {
    return NextResponse.json(
      { error: error.message || "Failed to retrieve profile" },
      { status: 500 }
    );
  }
}
