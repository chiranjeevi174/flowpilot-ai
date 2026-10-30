import { NextResponse } from "next/server";
import { setSessionCookies } from "@/lib/auth/session";

const BACKEND_URL = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const res = await fetch(`${BACKEND_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        {
          error: data.detail || "Authentication failed",
          detail: data.detail || "Authentication failed",
          error_code: data.error_code || "AUTH_FAILED",
        },
        { status: res.status }
      );
    }

    // Extract access_token and refresh_token from backend response / headers
    const accessToken = data.access_token;
    let refreshToken = data.refresh_token;

    // If backend sent refresh_token in a Set-Cookie header, extract it
    const setCookie = res.headers.get("set-cookie");
    if (setCookie && !refreshToken) {
      const match = setCookie.match(/refresh_token=([^;]+)/);
      if (match) {
        refreshToken = match[1];
      }
    }

    const response = NextResponse.json({
      success: true,
      expires_in: data.expires_in,
    });

    setSessionCookies(response.headers, accessToken, refreshToken, data.expires_in || 900);
    return response;
  } catch (error: any) {
    return NextResponse.json(
      { error: error.message || "Internal server error" },
      { status: 500 }
    );
  }
}
