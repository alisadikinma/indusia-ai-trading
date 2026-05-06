import { NextResponse, type NextRequest } from "next/server";
import {
  SESSION_COOKIE_NAME,
  SESSION_TTL_SECONDS,
  getOperatorPasswordHash,
  getOperatorUsername,
  signSession,
} from "@/lib/auth";
import { verifyPassword } from "@/lib/password";

// argon2 is a native Node binding — must run on the Node.js runtime, not Edge.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface LoginBody {
  username?: unknown;
  password?: unknown;
  next?: unknown;
}

export async function POST(req: NextRequest) {
  let body: LoginBody;
  try {
    body = (await req.json()) as LoginBody;
  } catch {
    return NextResponse.json(
      { error: "Malformed request body." },
      { status: 400 },
    );
  }

  const username = typeof body.username === "string" ? body.username : "";
  const password = typeof body.password === "string" ? body.password : "";
  const nextPathRaw = typeof body.next === "string" ? body.next : "/dashboard";
  // Only allow same-origin relative redirect targets.
  const nextPath = nextPathRaw.startsWith("/") && !nextPathRaw.startsWith("//")
    ? nextPathRaw
    : "/dashboard";

  if (!username || !password) {
    return NextResponse.json(
      { error: "Invalid credentials." },
      { status: 401 },
    );
  }

  const expectedUsername = getOperatorUsername();
  const expectedHash = getOperatorPasswordHash();

  // Always run argon2 verify even on bad username to keep timing roughly equal.
  const passwordOk = await verifyPassword(expectedHash, password);
  const usernameOk = username === expectedUsername;

  if (!usernameOk || !passwordOk) {
    return NextResponse.json(
      { error: "Invalid credentials." },
      { status: 401 },
    );
  }

  const token = await signSession(expectedUsername);
  const res = NextResponse.json({ ok: true, redirect: nextPath });
  res.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  });
  return res;
}
