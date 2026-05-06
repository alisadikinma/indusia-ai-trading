import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE_NAME, verifySession } from "@/lib/auth";

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
  const session = await verifySession(token);
  if (!session) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    const res = NextResponse.redirect(url);
    res.cookies.delete(SESSION_COOKIE_NAME);
    return res;
  }
  return NextResponse.next();
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
