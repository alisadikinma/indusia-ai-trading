// Next.js with `output: 'standalone'` writes a self-contained server tree to
// `.next/standalone/`, but the static asset bundles and `public/` files have
// to be copied alongside it manually. This is documented in the Next.js docs
// and is the same step the systemd unit relies on at deploy time.
//
// Running this as a build postbuild keeps `npm run start` (which boots
// `.next/standalone/server.js`) working out of the box for both Playwright
// and operator local smoke tests.

import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const standalone = resolve(root, ".next", "standalone");

if (!existsSync(standalone)) {
  console.error(
    "[postbuild-standalone] .next/standalone is missing — did `next build` run?",
  );
  process.exit(1);
}

const sources = [
  { from: resolve(root, ".next", "static"), to: resolve(standalone, ".next", "static") },
  { from: resolve(root, "public"), to: resolve(standalone, "public") },
];

for (const { from, to } of sources) {
  if (!existsSync(from)) continue;
  mkdirSync(dirname(to), { recursive: true });
  cpSync(from, to, { recursive: true, force: true });
  console.log(`[postbuild-standalone] copied ${from} -> ${to}`);
}
