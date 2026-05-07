import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE_NAME, revokeSession, verifySession } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  // Extract the JTI from the current session cookie and revoke it.
  const token = req.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (token) {
    const session = await verifySession(token);
    if (session) {
      try {
        await revokeSession(session.jti);
      } catch (error) {
        console.error("Failed to revoke session in database:", error);
        // Non-fatal: still clear the cookie and redirect.
      }
    }
  }

  const res = NextResponse.json({ ok: true, redirect: "/login" });
  res.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
  return res;
}
