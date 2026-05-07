import { SignJWT, jwtVerify, type JWTPayload } from "jose";
import { randomUUID } from "crypto";

export const SESSION_COOKIE_NAME = "bot_cockpit_session";
export const SESSION_TTL_SECONDS = 60 * 60 * 8; // 8h operator session

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value || value.length === 0) {
    throw new Error(
      `Missing required environment variable: ${name}. Refuse to start without explicit operator credentials.`,
    );
  }
  return value;
}

export function getJwtSecret(): Uint8Array {
  const secret = requireEnv("DASHBOARD_JWT_SECRET");
  if (secret.length < 32) {
    throw new Error(
      "DASHBOARD_JWT_SECRET must be at least 32 characters long.",
    );
  }
  return new TextEncoder().encode(secret);
}

export function getOperatorUsername(): string {
  return requireEnv("DASHBOARD_OPERATOR_USERNAME");
}

export function getOperatorPasswordHash(): string {
  return requireEnv("DASHBOARD_OPERATOR_PASSWORD_ARGON2_HASH");
}

export interface SessionPayload extends JWTPayload {
  sub: string;
  role: "operator";
  jti: string;
}

export async function signSession(username: string, jti?: string): Promise<string> {
  const secret = getJwtSecret();
  const sessionJti = jti ?? randomUUID();
  return new SignJWT({ sub: username, role: "operator", jti: sessionJti })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${SESSION_TTL_SECONDS}s`)
    .setIssuer("bot-cockpit")
    .setAudience("bot-cockpit-operator")
    .sign(secret);
}

export async function verifySession(
  token: string,
): Promise<SessionPayload | null> {
  try {
    const secret = getJwtSecret();
    const { payload } = await jwtVerify(token, secret, {
      issuer: "bot-cockpit",
      audience: "bot-cockpit-operator",
    });
    if (
      typeof payload.sub !== "string" ||
      payload.role !== "operator" ||
      typeof payload.jti !== "string"
    ) {
      return null;
    }
    // Defense-in-depth: check if JTI is still active in Postgres.
    const sessionPayload = payload as SessionPayload;
    const isActive = await checkSessionActive(sessionPayload.jti);
    if (!isActive) {
      return null;
    }
    return sessionPayload;
  } catch {
    return null;
  }
}

// Check if a session JTI is still active in the database.
export async function checkSessionActive(jti: string): Promise<boolean> {
  try {
    const { withDb } = await import("./db");
    return await withDb(async (client) => {
      const result = await client.query(
        `SELECT 1 FROM brain.active_sessions
         WHERE jti = $1 AND revoked_at IS NULL AND expires_at > now()`,
        [jti],
      );
      return result.rows.length > 0;
    });
  } catch {
    // On any DB error, fail closed: do not allow the session.
    return false;
  }
}

// Refresh session expiry (sliding window) and return a new token.
// Returns null on DB failure so callers can decide whether to keep the
// existing token vs force re-login. Non-fatal by default — the existing
// JWT is still valid until its natural expiry.
export async function refreshSession(
  sessionPayload: SessionPayload,
): Promise<string | null> {
  try {
    const { withDb } = await import("./db");
    await withDb(async (client) => {
      await client.query(
        `UPDATE brain.active_sessions
         SET expires_at = now() + ($2::int * interval '1 second')
         WHERE jti = $1 AND revoked_at IS NULL`,
        [sessionPayload.jti, SESSION_TTL_SECONDS],
      );
    });
    // Re-issue token with the same JTI (no new UUID).
    return await signSession(sessionPayload.sub, sessionPayload.jti);
  } catch (err) {
    // Log so operator sees DB outages instead of silent fallback (Iron Law 3 spirit).
    console.error("[auth] refreshSession failed:", err);
    return null;
  }
}

// Record a new session JTI in the database.
export async function recordSession(jti: string, username: string): Promise<void> {
  const { withDb } = await import("./db");
  await withDb(async (client) => {
    await client.query(
      `INSERT INTO brain.active_sessions (jti, sub, expires_at)
       VALUES ($1, $2, now() + ($3::int * interval '1 second'))`,
      [jti, username, SESSION_TTL_SECONDS],
    );
  });
}

// Revoke a session by JTI.
export async function revokeSession(jti: string): Promise<void> {
  const { withDb } = await import("./db");
  await withDb(async (client) => {
    await client.query(
      `UPDATE brain.active_sessions SET revoked_at = now() WHERE jti = $1`,
      [jti],
    );
  });
}

// Server Component helper: require a valid operator session.
//
// READ-ONLY. Server Components cannot mutate cookies in Next.js 15+
// (RequestCookiesAdapter throws ReadonlyRequestCookiesError) — sliding-window
// refresh and stale-cookie cleanup happen in `proxy.ts` middleware instead,
// which CAN set/delete cookies via `NextResponse.cookies.*`.
//
// Returns `{ wsToken, operator }` on success, or calls `redirect('/login')`
// (which throws — see Next.js docs) on missing/invalid/revoked session.
export async function requireOperatorSession(): Promise<{
  wsToken: string;
  operator: string;
}> {
  const { cookies } = await import("next/headers");
  const { redirect } = await import("next/navigation");

  const cookieStore = await cookies();
  const tokenValue = cookieStore.get(SESSION_COOKIE_NAME)?.value;

  if (!tokenValue) {
    redirect("/login");
  }

  const session = await verifySession(tokenValue as string);
  if (!session) {
    // Session invalid or revoked — middleware will clear the stale cookie
    // on the next request after this redirect lands the browser at /login.
    redirect("/login");
  }

  return {
    wsToken: tokenValue as string,
    operator: getOperatorUsername(),
  };
}
