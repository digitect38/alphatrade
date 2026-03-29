import { useApi } from "../hooks/useApi";
import type { HealthStatus } from "../types";

export default function SystemStatus({ t }: { t: (k: string) => string }) {
  const { data, error } = useApi<HealthStatus>("/health");

  return (
    <div className="card">
      <h3 className="card-title">{t("dash.systemStatus")}</h3>
      {error ? (
        <p className="text-loss">API Offline: {error}</p>
      ) : data ? (
        <div className="flex gap-xl">
          <span><span className={`status-dot ${data.status === "ok" ? "ok" : "error"}`} />API: {data.status}</span>
          <span><span className={`status-dot ${data.db === "ok" ? "ok" : "error"}`} />DB: {data.db}</span>
          <span><span className={`status-dot ${data.redis === "ok" ? "ok" : "error"}`} />Redis: {data.redis}</span>
        </div>
      ) : (
        <p className="text-secondary">{t("common.loading")}</p>
      )}
    </div>
  );
}
