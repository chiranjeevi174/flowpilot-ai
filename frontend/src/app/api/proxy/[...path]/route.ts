import { NextRequest, NextResponse } from "next/server";
import {
  clearSessionCookies,
  getSessionTokens,
  refreshAccessToken,
  setSessionCookies,
} from "@/lib/auth/session";

const BACKEND_URL = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";

async function handleProxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  try {
    const { path } = await context.params;
    const targetPath = path.join("/");
    const searchParams = request.nextUrl.searchParams.toString();
    const targetUrl = `${BACKEND_URL}/api/v1/${targetPath}${
      searchParams ? `?${searchParams}` : ""
    }`;

    const tokens = await getSessionTokens();
    let accessToken = tokens.accessToken;
    const refreshToken = tokens.refreshToken;
    let refreshedTokens: { accessToken: string; refreshToken?: string; expiresIn: number } | null =
      null;

    // Refresh if access token is absent but refresh token exists
    if (!accessToken && refreshToken) {
      refreshedTokens = await refreshAccessToken(refreshToken);
      if (refreshedTokens) {
        accessToken = refreshedTokens.accessToken;
      }
    }

    const headers: Record<string, string> = {};
    if (accessToken) {
      headers["Authorization"] = `Bearer ${accessToken}`;
    }

    const contentType = request.headers.get("content-type");
    if (contentType) {
      headers["Content-Type"] = contentType;
    }

    const method = request.method;
    let body: any = undefined;
    if (method !== "GET" && method !== "HEAD") {
      const text = await request.text();
      if (text) {
        body = text;
      }
    }

    let backendRes = await fetch(targetUrl, {
      method,
      headers,
      body,
    });

    // If 401 Unauthorized and refresh token available, retry once after refreshing
    if (backendRes.status === 401 && refreshToken) {
      refreshedTokens = await refreshAccessToken(refreshToken);
      if (refreshedTokens) {
        accessToken = refreshedTokens.accessToken;
        headers["Authorization"] = `Bearer ${accessToken}`;
        backendRes = await fetch(targetUrl, {
          method,
          headers,
          body,
        });
      }
    }

    // 204 No Content
    if (backendRes.status === 204) {
      const response = new NextResponse(null, { status: 204 });
      if (refreshedTokens) {
        setSessionCookies(
          response.headers,
          refreshedTokens.accessToken,
          refreshedTokens.refreshToken,
          refreshedTokens.expiresIn
        );
      }
      return response;
    }

    const responseHeaders = new Headers();
    const resContentType = backendRes.headers.get("content-type");
    if (resContentType) {
      responseHeaders.set("Content-Type", resContentType);
    }

    if (refreshedTokens) {
      setSessionCookies(
        responseHeaders,
        refreshedTokens.accessToken,
        refreshedTokens.refreshToken,
        refreshedTokens.expiresIn
      );
    }

    // If refresh failed and backend is still 401, clear cookies
    if (backendRes.status === 401) {
      clearSessionCookies(responseHeaders);
    }

    return new NextResponse(backendRes.body, {
      status: backendRes.status,
      headers: responseHeaders,
    });
  } catch (error: any) {
    console.error("API proxy error:", error);
    return NextResponse.json(
      { error: error.message || "Failed to proxy request" },
      { status: 502 }
    );
  }
}

export const GET = handleProxy;
export const POST = handleProxy;
export const PUT = handleProxy;
export const PATCH = handleProxy;
export const DELETE = handleProxy;
