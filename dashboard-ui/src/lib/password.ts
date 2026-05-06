import argon2 from "argon2";

/**
 * Verify a plaintext password against an argon2 hash from the operator
 * environment. Uses argon2's built-in constant-time comparison.
 */
export async function verifyPassword(
  hash: string,
  plain: string,
): Promise<boolean> {
  if (!hash || !plain) return false;
  try {
    return await argon2.verify(hash, plain);
  } catch {
    return false;
  }
}

/**
 * Operator setup helper. Run via:
 *   node -e "require('./src/lib/password').hashPassword('mypw').then(console.log)"
 */
export async function hashPassword(plain: string): Promise<string> {
  return argon2.hash(plain, { type: argon2.argon2id });
}
