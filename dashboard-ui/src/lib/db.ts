import { Pool, type PoolClient } from "pg";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value || value.length === 0) {
    throw new Error(
      `Missing required environment variable: ${name}. Refuse to start without explicit database credentials.`,
    );
  }
  return value;
}

// Singleton pool, reused across all requests.
let pool: Pool | null = null;

export function getPool(): Pool {
  if (!pool) {
    const databaseUrl = requireEnv("DATABASE_URL");
    pool = new Pool({
      connectionString: databaseUrl,
      // Conservative: small connections to avoid overwhelming the Postgres host.
      // Each Next.js server process has its own pool.
      max: 10,
      idleTimeoutMillis: 30000,
      connectionTimeoutMillis: 5000,
    });
  }
  return pool;
}

export async function withDb<T>(
  fn: (client: PoolClient) => Promise<T>,
): Promise<T> {
  const pool = getPool();
  const client = await pool.connect();
  try {
    return await fn(client);
  } finally {
    client.release();
  }
}
