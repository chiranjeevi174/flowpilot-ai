import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const token = searchParams.get("token");

    if (!token) {
      return NextResponse.json(
        { valid: false, reason: "Missing reset token" },
        { status: 400 }
      );
    }

    const res = await fetch(
      `${BACKEND_URL}/api/v1/auth/reset-password/validate?token=${encodeURIComponent(token)}`,
      {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      }
    );

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error: any) {
    return NextResponse.json(
      { valid: false, reason: error.message || "Failed to validate reset token" },
      { status: 500 }
    );
  }
}
