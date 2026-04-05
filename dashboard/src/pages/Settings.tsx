import { useEffect, useState } from "react";
import { apiGet, apiPut } from "../hooks/useApi";

interface SettingField {
  label: string;
  type: "text" | "secret" | "select";
  options?: string[];
  default: string;
  group: string;
  value: string;
  is_set: boolean;
}

export default function SettingsPage({ t: _t }: { t: (k: string) => string }) {
  const [settings, setSettings] = useState<Record<string, SettingField>>({});
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiGet<{ settings: Record<string, SettingField> }>("/settings")
      .then((d) => {
        setSettings(d.settings);
        const init: Record<string, string> = {};
        for (const [k, v] of Object.entries(d.settings)) {
          init[k] = v.value;
        }
        setDraft(init);
      })
      .catch(() => setMessage(_t("settings.loadError")))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage("");
    try {
      const changed: Record<string, string> = {};
      for (const [k, v] of Object.entries(draft)) {
        if (v !== settings[k]?.value) {
          changed[k] = v;
        }
      }
      if (Object.keys(changed).length === 0) {
        setMessage(_t("settings.noChanges"));
        setSaving(false);
        return;
      }
      await apiPut("/settings", { settings: changed });
      setMessage(_t("settings.saved"));
      // Reload to get updated masked values
      const d = await apiGet<{ settings: Record<string, SettingField> }>("/settings");
      setSettings(d.settings);
      const init: Record<string, string> = {};
      for (const [k, v] of Object.entries(d.settings)) init[k] = v.value;
      setDraft(init);
    } catch (e: any) {
      setMessage(`${_t("settings.saveError")}: ${e.message}`);
    }
    setSaving(false);
  };

  if (loading) return <p className="text-secondary p-xl">{_t("settings.loading")}</p>;

  // Group settings
  const groups: Record<string, [string, SettingField][]> = {};
  for (const [k, v] of Object.entries(settings)) {
    const g = v.group || "general";
    if (!groups[g]) groups[g] = [];
    groups[g].push([k, v]);
  }

  const groupLabels: Record<string, string> = {
    llm: _t("settings.groupLlm"),
    telegram: _t("settings.groupTelegram"),
    general: _t("settings.groupGeneral"),
  };

  return (
    <div className="page-content">
      {Object.entries(groups).map(([group, fields]) => (
        <section key={group} className="card" style={{ marginBottom: "16px" }}>
          <h3 className="card-title">{groupLabels[group] || group}</h3>
          <div className="settings-grid">
            {fields.map(([key, field]) => (
              <div key={key} className="settings-row">
                <label className="settings-label">
                  {field.label}
                  {field.is_set && field.type === "secret" && (
                    <span className="settings-badge">{_t("settings.configured")}</span>
                  )}
                </label>
                {field.type === "select" ? (
                  <select
                    className="settings-input"
                    value={draft[key] || ""}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  >
                    {field.options?.map((opt) => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type === "secret" ? "password" : "text"}
                    className="settings-input"
                    value={draft[key] || ""}
                    placeholder={field.type === "secret" ? "sk-..." : ""}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                    onFocus={(e) => {
                      // Clear masked value on focus so user can type fresh
                      if (field.type === "secret" && e.target.value.includes("••••")) {
                        setDraft({ ...draft, [key]: "" });
                      }
                    }}
                  />
                )}
              </div>
            ))}
          </div>
        </section>
      ))}

      <div className="settings-actions">
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? _t("settings.saving") : _t("settings.save")}
        </button>
        {message && <span className="settings-message">{message}</span>}
      </div>
    </div>
  );
}
