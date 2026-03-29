import { useEffect, useRef, useState } from "react";
import { apiGet } from "../hooks/useApi";

interface StockItem {
  stock_code: string;
  stock_name: string;
  market: string;
  sector: string;
  label: string;
}

interface Props {
  value: string;
  onChange: (code: string, name: string) => void;
  placeholder?: string;
}

export default function StockSearch({ value, onChange, placeholder }: Props) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<StockItem[]>([]);
  const [open, setOpen] = useState(false);
  const [selectedName, setSelectedName] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const search = (q: string) => {
    if (q.length < 1) {
      setResults([]);
      setOpen(false);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      apiGet<StockItem[]>(`/market/search?q=${encodeURIComponent(q)}`)
        .then((items) => {
          setResults(items);
          setOpen(items.length > 0);
        })
        .catch(() => setResults([]));
    }, 200);
  };

  const handleInput = (val: string) => {
    setQuery(val);
    setSelectedName("");
    search(val);
    // If user types a raw code, propagate it
    if (/^\d{6}$/.test(val)) {
      onChange(val, "");
    }
  };

  const handleSelect = (item: StockItem) => {
    setQuery(item.stock_code);
    setSelectedName(item.stock_name);
    setOpen(false);
    onChange(item.stock_code, item.stock_name);
  };

  return (
    <div ref={wrapperRef} style={{ position: "relative", display: "inline-block" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
        <input
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder={placeholder || "종목명 or 코드"}
          style={{
            padding: "8px 12px", border: "1px solid #ddd", borderRadius: "6px",
            fontSize: "14px", width: "160px",
          }}
        />
        {selectedName && (
          <span style={{ fontSize: "13px", fontWeight: 600, color: "#1a1a2e" }}>
            {selectedName}
          </span>
        )}
      </div>

      {open && results.length > 0 && (
        <div
          style={{
            position: "absolute", top: "100%", left: 0, right: 0,
            background: "#fff", border: "1px solid #e0e0e0", borderRadius: "8px",
            boxShadow: "0 8px 24px rgba(0,0,0,0.12)", zIndex: 100,
            maxHeight: "240px", overflowY: "auto", marginTop: "4px",
          }}
        >
          {results.map((item) => (
            <div
              key={item.stock_code}
              onClick={() => handleSelect(item)}
              style={{
                padding: "10px 14px", cursor: "pointer", fontSize: "13px",
                borderBottom: "1px solid #f5f5f5", transition: "background 0.1s",
              }}
              onMouseOver={(e) => (e.currentTarget.style.background = "#f0f7ff")}
              onMouseOut={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <div style={{ fontWeight: 600 }}>
                {item.stock_name}
                <span style={{ color: "#888", fontWeight: 400, marginLeft: "8px" }}>{item.stock_code}</span>
              </div>
              <div style={{ fontSize: "11px", color: "#999", marginTop: "2px" }}>
                {item.market} · {item.sector || "-"}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
