"use client";

// WebSocket client for /dashboard/ws.
//
// Hard-fails if NEXT_PUBLIC_DASHBOARD_WS_URL is missing — Iron Law 3.
// Auto-reconnects with exponential backoff (1s, 2s, 4s, 8s, 16s, capped at 30s)
// plus jitter, and replies to server pings with pong.

import { useEffect, useRef, useState } from "react";

import type { WsMessage } from "./api-types";

function requireWsUrl(): string {
  const v = process.env.NEXT_PUBLIC_DASHBOARD_WS_URL;
  if (!v || v.length === 0) {
    throw new Error(
      "Missing required public environment variable: NEXT_PUBLIC_DASHBOARD_WS_URL.",
    );
  }
  return v;
}

export type WsConnectionState = "connecting" | "open" | "closed" | "error";

export interface UseDashboardWsResult {
  state: WsConnectionState;
  lastMessage: WsMessage | null;
  // The full sequence of channel events received in this session (ring-buffered).
  messages: WsMessage[];
}

const MAX_BUFFER = 200;

export function useDashboardWs(
  channels: ReadonlyArray<NonNullable<WsMessage["channel"]>>,
  token: string | null,
): UseDashboardWsResult {
  const [state, setState] = useState<WsConnectionState>("connecting");
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);
  const messagesRef = useRef<WsMessage[]>([]);
  const [, forceRender] = useState(0);

  useEffect(() => {
    if (!token) {
      setState("closed");
      return;
    }

    let attempt = 0;
    let ws: WebSocket | null = null;
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      const baseUrl = requireWsUrl();
      // The server expects ?token=<jwt>. Append carefully.
      const sep = baseUrl.includes("?") ? "&" : "?";
      const url = `${baseUrl}${sep}token=${encodeURIComponent(token)}`;

      setState("connecting");
      ws = new WebSocket(url);

      ws.onopen = () => {
        attempt = 0;
        setState("open");
        // Optional fine-grained subscription (server currently broadcasts all 3 channels).
        try {
          ws?.send(JSON.stringify({ type: "subscribe", channels }));
        } catch {
          // ignore
        }
      };

      ws.onmessage = (ev) => {
        let parsed: WsMessage;
        try {
          parsed = JSON.parse(ev.data) as WsMessage;
        } catch {
          return;
        }
        if (parsed.type === "ping") {
          try {
            ws?.send(JSON.stringify({ type: "pong" }));
          } catch {
            // ignore
          }
          return;
        }
        // Filter to subscribed channels client-side.
        if (parsed.channel && !channels.includes(parsed.channel)) return;
        setLastMessage(parsed);
        const buf = messagesRef.current;
        buf.push(parsed);
        if (buf.length > MAX_BUFFER) buf.splice(0, buf.length - MAX_BUFFER);
        forceRender((n) => n + 1);
      };

      ws.onerror = () => {
        setState("error");
      };

      ws.onclose = () => {
        if (cancelled) return;
        setState("closed");
        attempt += 1;
        const base = Math.min(30_000, 1000 * 2 ** Math.min(attempt - 1, 5));
        const jitter = Math.random() * 250;
        reconnectTimer = setTimeout(connect, base + jitter);
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      try {
        ws?.close();
      } catch {
        // ignore
      }
    };
  }, [channels, token]);

  return { state, lastMessage, messages: messagesRef.current };
}
