import { SignJWT, jwtVerify, type JWTPayload } from "jose";

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
}

export async function signSession(username: string): Promise<string> {
  const secret = getJwtSecret();
  return new SignJWT({ sub: username, role: "operator" })
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
      payload.role !== "operator"
    ) {
      return null;
    }
    return payload as SessionPayload;
  } catch {
    return null;
  }
}
