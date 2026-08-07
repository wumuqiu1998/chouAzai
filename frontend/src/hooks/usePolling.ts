// 通用轮询：与 useLiveQuotes 相同的纪律（递归 setTimeout、交易时段暂停、
// 页面切走暂停、失败退避、成功后复位）。
import { useCallback, useEffect, useRef, useState } from "react";
import { isTradingHours } from "@/hooks/useLiveQuotes";

const MAX_BACKOFF_MS = 30_000;

export interface PollingState<T> {
  data: T | null;
  error: string | null;
  updatedAt: number | null;
  polling: boolean;
  refresh: () => void;
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  enabled: boolean,
  pauseOutsideTrading = true,
): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [polling, setPolling] = useState(false);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const failuresRef = useRef(0);
  const inFlightRef = useRef(false);
  const fetchRef = useRef<(() => Promise<boolean>) | null>(null);

  const fetchOnce = useCallback(async (): Promise<boolean> => {
    if (inFlightRef.current) return true;
    inFlightRef.current = true;
    try {
      const value = await fetcherRef.current();
      setData(value);
      setUpdatedAt(Date.now());
      setError(null);
      failuresRef.current = 0;
      return true;
    } catch {
      failuresRef.current += 1;
      if (failuresRef.current >= 2) setError("数据获取失败，正在重试…");
      return false;
    } finally {
      inFlightRef.current = false;
    }
  }, []);
  fetchRef.current = fetchOnce;

  const refresh = useCallback(() => {
    void fetchOnce();
  }, [fetchOnce]);

  useEffect(() => {
    void fetchOnce();
  }, [fetchOnce]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    const clear = () => {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    };
    const shouldRun = () =>
      enabled && !document.hidden && (!pauseOutsideTrading || isTradingHours());

    const loop = async () => {
      if (cancelled) return;
      if (!shouldRun()) {
        setPolling(false);
        timer = window.setTimeout(loop, 10_000);
        return;
      }
      setPolling(true);
      const ok = await fetchOnce();
      if (cancelled) return;
      const wait = ok ? intervalMs : Math.min(intervalMs * 2 ** failuresRef.current, MAX_BACKOFF_MS);
      timer = window.setTimeout(loop, wait);
    };

    if (enabled) {
      void loop();
    } else {
      setPolling(false);
    }

    const onVisible = () => {
      if (!document.hidden && enabled && !cancelled) {
        clear();
        void loop();
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      clear();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, intervalMs, pauseOutsideTrading, fetchOnce]);

  return { data, error, updatedAt, polling, refresh };
}
