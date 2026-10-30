import { NextRequest, NextResponse } from "next/server";
import { getSessionTokens, refreshAccessToken } from "@/lib/auth/session";

const BACKEND_URL = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await context.params;
    const tokens = await getSessionTokens();
    let accessToken = tokens.accessToken;
    const refreshToken = tokens.refreshToken;

    if (!accessToken && refreshToken) {
      const refreshed = await refreshAccessToken(refreshToken);
      if (refreshed) {
        accessToken = refreshed.accessToken;
      }
    }

    if (!accessToken) {
      return new NextResponse("Unauthorized", { status: 401 });
    }

    const lastEventId = request.headers.get("Last-Event-ID") || request.nextUrl.searchParams.get("last_event_id");
    const targetUrl = `${BACKEND_URL}/api/v1/agents/runs/${id}/stream${
      lastEventId ? `?last_event_id=${encodeURIComponent(lastEventId)}` : ""
    }`;

    const headers: Record<string, string> = {
      Authorization: `Bearer ${accessToken}`,
      Accept: "text/event-stream",
    };
    if (lastEventId) {
      headers["Last-Event-ID"] = lastEventId;
    }

    const backendRes = await fetch(targetUrl, {
      method: "GET",
      headers,
    });

    if (!backendRes.ok || !backendRes.body) {
      return new NextResponse(backendRes.statusText || "Failed to establish SSE stream", {
        status: backendRes.status,
      });
    }

    // Pipe SSE stream directly to browser
    return new NextResponse(backendRes.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (error: any) {
    console.error("SSE stream proxy error:", error);
    return new NextResponse(error.message || "SSE proxy error", { status: 502 });
  }
}
