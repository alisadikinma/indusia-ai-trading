import { NextResponse, type NextRequest } from "next/server";
import {
  SESSION_COOKIE_NAME,
  SESSION_TTL_SECONDS,
  refreshSession,
  verifySession,
} from "@/lib/auth";

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/strategy-lab",
  "/journal",
  "/freqai",
  "/iteration-history",
];

export async function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const isProtected = PROTECTED_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
  if (!isProtected) return NextResponse.next();

  const token = req.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!token) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  // Middleware defense-in-depth: verify session (includes DB revocation check).
  const session = await verifySession(token);
  if (!session) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    const res = NextResponse.redirect(url);
    res.cookies.delete(SESSION_COOKIE_NAME);
    return res;
  }

  // Sliding-window refresh: extend expires_at in DB and rotate cookie. Cookie
  // mutation lives here (Node middleware) because Server Components can't
  // write cookies in Next.js 15+ (ReadonlyRequestCookiesError). On refresh
  // failure, leave the existing cookie in place — the JWT is still valid
  // until its natural expiry.
  const res = NextResponse.next();
  const newToken = await refreshSession(session);
  if (newToken) {
    res.cookies.set({
      name: SESSION_COOKIE_NAME,
      value: newToken,
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: SESSION_TTL_SECONDS,
    });
  }
  return res;
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/strategy-lab/:path*",
    "/journal/:path*",
    "/freqai/:path*",
    "/iteration-history/:path*",
  ],
};
