import { useEffect, useRef, useState, useCallback } from "react";

interface RealtimeTick {
  stock_code: string;
  price: number;
  change: number;
  change_pct: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  time: string;
  received_at: string;
}

interface UseWebSocketOptions {
  stockCodes?: string[];
  onTick?: (tick: RealtimeTick) => void;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const [connected, setConnected] = useState(false);
  const [lastTick, setLastTick] = useState<RealtimeTick | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      // Subscribe to specific stocks if provided
      if (options.stockCodes && options.stockCodes.length > 0) {
        ws.send(JSON.stringify({ subscribe: options.stockCodes }));
      }
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "heartbeat" || data.type === "pong" || data.type === "subscribed") {
          return;
        }
        // Real-time tick
        if (data.stock_code) {
          const tick = data as RealtimeTick;
          setLastTick(tick);
          options.onTick?.(tick);
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Auto-reconnect after 5 seconds
      reconnectRef.current = setTimeout(connect, 5000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [options.stockCodes?.join(",")]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  return { connected, lastTick };
}
