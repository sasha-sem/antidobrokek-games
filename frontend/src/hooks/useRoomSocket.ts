import { useCallback, useEffect, useRef, useState } from "react";
import type { ServerEnvelope } from "../types/events";

export type SocketStatus = "connecting" | "connected" | "reconnecting" | "closed";

export function useRoomSocket(
  code: string,
  role: "host" | "player",
  token: string,
  onEvent: (event: ServerEnvelope) => void,
) {
  const socketRef = useRef<WebSocket | null>(null);
  const callbackRef = useRef(onEvent);
  const retryRef = useRef(0);
  const timerRef = useRef<number | undefined>(undefined);
  const pingTimes = useRef(new Map<string, number>());
  const [status, setStatus] = useState<SocketStatus>("connecting");
  const [serverOffsetMs, setServerOffsetMs] = useState(0);
  callbackRef.current = onEvent;

  useEffect(() => {
    let disposed = false;
    let pingTimer: number | undefined;

    const connect = () => {
      setStatus(retryRef.current ? "reconnecting" : "connecting");
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${protocol}://${location.host}/ws/rooms/${encodeURIComponent(code)}`);
      socketRef.current = socket;
      socket.onopen = () => {
        retryRef.current = 0;
        setStatus("connected");
        socket.send(JSON.stringify({ type: "authenticate", payload: { role, token } }));
        pingTimer = window.setInterval(() => {
          if (socket.readyState !== WebSocket.OPEN) return;
          const requestId = crypto.randomUUID();
          const clientTime = Date.now();
          pingTimes.current.set(requestId, clientTime);
          socket.send(JSON.stringify({ type: "ping", request_id: requestId, payload: { client_time: clientTime } }));
        }, 5000);
      };
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data as string) as ServerEnvelope;
        if (event.type === "pong" && event.request_id) {
          const sentAt = pingTimes.current.get(event.request_id);
          if (sentAt) {
            setServerOffsetMs(new Date(event.server_time).getTime() - (sentAt + Date.now()) / 2);
            pingTimes.current.delete(event.request_id);
          }
        }
        callbackRef.current(event);
      };
      socket.onclose = (event) => {
        window.clearInterval(pingTimer);
        if (disposed || event.code === 4000 || event.code === 4003) {
          setStatus("closed");
          return;
        }
        setStatus("reconnecting");
        const delay = Math.min(1000 * 2 ** retryRef.current, 15000);
        retryRef.current += 1;
        timerRef.current = window.setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(timerRef.current);
      window.clearInterval(pingTimer);
      socketRef.current?.close();
    };
  }, [code, role, token]);

  const send = useCallback((type: string, payload: Record<string, unknown> = {}) => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return false;
    socketRef.current.send(JSON.stringify({ type, request_id: crypto.randomUUID(), payload }));
    return true;
  }, []);

  return { status, serverOffsetMs, send };
}
