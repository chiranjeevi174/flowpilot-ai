import { NextResponse } from "next/server";
import { setSessionCookies } from "@/lib/auth/session";

const BACKEND_URL = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const res = await fetch(`${BACKEND_URL}/api/v1/auth/dev-impersonate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(
        { error: data.detail || "Impersonation failed" },
        { status: res.status }
      );
    }

    const response = NextResponse.json({
      success: true,
      email: body.email,
    });

    setSessionCookies(response.headers, data.access_token, undefined, data.expires_in || 3600);
    return response;
  } catch (error: any) {
    return NextResponse.json(
      { error: error.message || "Internal server error" },
      { status: 500 }
    );
  }
}
