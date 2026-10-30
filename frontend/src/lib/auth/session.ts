import { cookies } from "next/headers";

const BACKEND_URL = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";

export interface SessionTokens {
  accessToken: string | null;
  refreshToken: string | null;
}

/**
 * Extract tokens from server-side HttpOnly cookies.
 */
export async function getSessionTokens(): Promise<SessionTokens> {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get("access_token")?.value || null;
  const refreshToken = cookieStore.get("refresh_token")?.value || null;
  return { accessToken, refreshToken };
}

/**
 * Set session cookies on response.
 */
export function setSessionCookies(
  headers: Headers,
  accessToken: string,
  refreshToken?: string,
  expiresInSeconds: number = 900
) {
  const isProd = process.env.NODE_ENV === "production";
  
  // Access token cookie (15 mins default)
  headers.append(
    "Set-Cookie",
    `access_token=${accessToken}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${expiresInSeconds}${
      isProd ? "; Secure" : ""
    }`
  );

  // Refresh token cookie (7 days default)
  if (refreshToken) {
    headers.append(
      "Set-Cookie",
      `refresh_token=${refreshToken}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${7 * 86400}${
        isProd ? "; Secure" : ""
      }`
    );
  }
}

/**
 * Clear session cookies on response.
 */
export function clearSessionCookies(headers: Headers) {
  const isProd = process.env.NODE_ENV === "production";
  headers.append(
    "Set-Cookie",
    `access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${isProd ? "; Secure" : ""}`
  );
  headers.append(
    "Set-Cookie",
    `refresh_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${isProd ? "; Secure" : ""}`
  );
}

// In-flight refresh promise map keyed by refreshToken to deduplicate concurrent requests
const activeRefreshPromises = new Map<
  string,
  Promise<{
    accessToken: string;
    refreshToken?: string;
    expiresIn: number;
  } | null>
>();

/**
 * Server-side helper to refresh an expired access token using the refresh_token cookie.
 * Deduplicates concurrent requests for the same refresh token.
 */
export async function refreshAccessToken(refreshToken: string): Promise<{
  accessToken: string;
  refreshToken?: string;
  expiresIn: number;
} | null> {
  const existingPromise = activeRefreshPromises.get(refreshToken);
  if (existingPromise) {
    return existingPromise;
  }

  const refreshPromise = (async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/v1/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!res.ok) {
        return null;
      }

      const data = await res.json();
      return {
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresIn: data.expires_in || 900,
      };
    } catch (err) {
      console.error("Failed to refresh token:", err);
      return null;
    } finally {
      activeRefreshPromises.delete(refreshToken);
    }
  })();

  activeRefreshPromises.set(refreshToken, refreshPromise);
  return refreshPromise;
}
