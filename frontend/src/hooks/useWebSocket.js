import { useEffect, useRef, useCallback, useState } from 'react';

const WS_URL = 'ws://127.0.0.1:8088/ws';

/**
 * Custom hook for WebSocket communication with the backend.
 * Auto-reconnects on disconnect. Provides typed message handlers.
 */
export function useWebSocket(handlers = {}) {
  const wsRef = useRef(null);
  const handlersRef = useRef(handlers);
  const reconnectTimer = useRef(null);
  const [connected, setConnected] = useState(false);

  const isMounted = useRef(true);

  // Keep handlers ref current
  handlersRef.current = handlers;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      if (!isMounted.current) {
        ws.close();
        return;
      }
      setConnected(true);
      // Send ping to verify
      ws.send(JSON.stringify({ type: 'ping' }));
    };

    ws.onmessage = (event) => {
      if (ws !== wsRef.current) return; // Ignore messages from old websockets
      if (!isMounted.current) return;
      try {
        const msg = JSON.parse(event.data);
        const handler = handlersRef.current[msg.type];
        if (handler) {
          handler(msg.data);
        }
        // Also call the catch-all handler if provided
        if (handlersRef.current.onMessage) {
          handlersRef.current.onMessage(msg);
        }
      } catch (e) {
        console.error('WebSocket message parse error:', e);
      }
    };

    ws.onclose = () => {
      if (!isMounted.current) return;
      setConnected(false);
      // Auto-reconnect after 2 seconds
      reconnectTimer.current = setTimeout(connect, 2000);
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    isMounted.current = true;
    connect();
    return () => {
      isMounted.current = false;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((type, data = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, ...data }));
    }
  }, []);

  const sendInput = useCallback((text) => {
    send('input', { text });
  }, [send]);

  const respondPermission = useCallback((granted) => {
    send('permission', { granted });
  }, [send]);

  const cancel = useCallback(() => {
    send('cancel');
  }, [send]);

  return { connected, send, sendInput, respondPermission, cancel };
}
