import { useCallback, useEffect, useRef, useState } from "react";
import type { JarvisBridge } from "../../shared/contracts";

declare global {
  interface Window {
    jarvis?: JarvisBridge;
  }
}

export const bridge = (): JarvisBridge | null =>
  typeof window !== "undefined" && window.jarvis ? window.jarvis : null;

export interface ApiResult<T> {
  ok: boolean;
  status: number;
  data: T | null;
  error?: string;
}

export async function api<T = any>(path: string, options: { method?: string; body?: unknown } = {}): Promise<ApiResult<T>> {
  const method = options.method || "GET";
  const native = bridge();
  if (native) {
    try {
      return (await native.request<T>(method, path, options.body)) as ApiResult<T>;
    } catch (error) {
      return { ok: false, status: 0, data: null, error: String(error) };
    }
  }
  try {
    const response = await fetch(path, {
      method,
      headers: options.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
    const text = await response.text();
    let data: any = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { raw: text };
    }
    return {
      ok: response.ok,
      status: response.status,
      data,
      error: response.ok ? undefined : data?.detail || `HTTP ${response.status}`,
    };
  } catch (error) {
    return { ok: false, status: 0, data: null, error: String(error) };
  }
}

export function useApi<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    const result = await api<T>(path);
    if (!mounted.current) return;
    if (result.ok) {
      setData(result.data);
      setError(null);
    } else {
      setError(result.error || "Falha na requisicao");
    }
    setLoading(false);
  }, [path]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  return { data, error, loading, refresh, setData };
}

export function usePolling(path: string | null, intervalMs = 5000, deps: unknown[] = []) {
  const state = useApi<any>(path, deps);
  const { refresh } = state;
  useEffect(() => {
    if (!path) return;
    const timer = window.setInterval(() => void refresh(), intervalMs);
    return () => window.clearInterval(timer);
  }, [path, intervalMs, refresh]);
  return state;
}

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return "sem dado";
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export function formatDate(value?: string | null): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return value;
  }
}

export function shortId(value?: string | null): string {
  if (!value) return "-";
  return value.length > 16 ? `${value.slice(0, 12)}…` : value;
}
