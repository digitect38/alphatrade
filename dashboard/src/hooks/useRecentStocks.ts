import { useState, useCallback } from "react";

const STORAGE_KEY = "alphatrade_recent_stocks";
const MAX_RECENT = 10;

export interface RecentStock {
  code: string;
  name: string;
  timestamp: number;
}

function loadFromStorage(): RecentStock[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveToStorage(stocks: RecentStock[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(stocks));
}

export function useRecentStocks() {
  const [recentStocks, setRecentStocks] = useState<RecentStock[]>(loadFromStorage);

  const recordStock = useCallback((code: string, name: string) => {
    if (!/^\d{6}$/.test(code) || !name) return;
    setRecentStocks((prev) => {
      const filtered = prev.filter((s) => s.code !== code);
      const next = [{ code, name, timestamp: Date.now() }, ...filtered].slice(0, MAX_RECENT);
      saveToStorage(next);
      return next;
    });
  }, []);

  return { recentStocks, recordStock };
}
