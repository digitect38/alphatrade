import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { marked } from "marked";
import katex from "katex";
import "katex/dist/katex.min.css";
import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import json from "highlight.js/lib/languages/json";
import sql from "highlight.js/lib/languages/sql";
import bash from "highlight.js/lib/languages/bash";
import "highlight.js/styles/github-dark.css";
import DOMPurify from "dompurify";
import { apiGet, apiDelete } from "../hooks/useApi";

hljs.registerLanguage("python", python);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("bash", bash);

// Configure marked with syntax highlighting
marked.setOptions({
  breaks: true,
  gfm: true,
});

const renderer = new marked.Renderer();
renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
  const language = lang && hljs.getLanguage(lang) ? lang : "";
  const highlighted = language
    ? hljs.highlight(text, { language }).value
    : hljs.highlightAuto(text).value;
  return `<pre><code class="hljs${language ? ` language-${language}` : ""}">${highlighted}</code></pre>`;
};
marked.use({ renderer });

/**
 * Render LaTeX in markdown content.
 *
 * Strategy: extract LaTeX BEFORE markdown parsing to prevent marked from
 * escaping/wrapping math in code blocks. Replace with placeholders,
 * run marked, then restore with KaTeX-rendered HTML.
 */
function renderMarkdownWithLatex(content: string): string {
  const placeholders: Record<string, string> = {};
  let idx = 0;

  function placeholder(tex: string, display: boolean): string {
    const key = `%%LATEX_${idx++}%%`;
    try {
      placeholders[key] = katex.renderToString(tex.trim(), { displayMode: display, throwOnError: false });
    } catch {
      placeholders[key] = `<code>${tex}</code>`;
    }
    return key;
  }

  // Strip ```latex code blocks — unwrap the LaTeX inside
  let text = content.replace(/```latex\s*\n?([\s\S]*?)```/g, (_, inner) => inner.trim());

  // Display math: $$...$$ or \[...\]
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => placeholder(tex, true));
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => placeholder(tex, true));

  // Inline math: $...$ or \(...\)
  text = text.replace(/(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)/g, (_, tex) => placeholder(tex, false));
  text = text.replace(/\\\((.+?)\\\)/g, (_, tex) => placeholder(tex, false));

  // Now parse markdown
  let html = marked.parse(text) as string;

  // Restore placeholders
  for (const [key, rendered] of Object.entries(placeholders)) {
    html = html.replace(key, rendered);
  }

  return html;
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  image?: string; // data URL for display
  ts?: string;
}

export default function LLMChatPage({ t: _t }: { t: (k: string) => string }) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [model, setModel] = useState("");
  const [imageData, setImageData] = useState<string | null>(null);
  const [sessionId] = useState(() => `web-${Date.now()}`);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const promptHistory = useRef<string[]>([]);
  const historyIdx = useRef(-1);
  const savedInput = useRef("");

  // Load history
  useEffect(() => {
    apiGet<{ messages: ChatMsg[] }>(`/llm/history?session_id=${sessionId}`)
      .then((d) => { if (d.messages?.length) setMessages(d.messages); })
      .catch(() => {});
  }, [sessionId]);

  // Auto scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text && !imageData) return;
    if (loading) return;
    const img = imageData;
    if (text) {
      promptHistory.current.push(text);
      historyIdx.current = -1;
      savedInput.current = "";
    }
    setInput("");
    setImageData(null);
    setMessages((prev) => [...prev, { role: "user", content: text || "(이미지)", image: img || undefined }]);
    setLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await fetch("/api/llm/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text || "이 이미지를 분석해주세요.",
          session_id: sessionId,
          ...(img ? { image: img } : {}),
        }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
      if (data.model) setModel(data.model);
    } catch (e: any) {
      if (e.name === "AbortError") {
        setMessages((prev) => [...prev, { role: "assistant", content: "(답변 중지됨)" }]);
      } else {
        setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${e.message}` }]);
      }
    }
    abortRef.current = null;
    setLoading(false);
    inputRef.current?.focus();
  }, [input, imageData, loading, sessionId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
      return;
    }
    const hist = promptHistory.current;
    if (e.key === "ArrowUp" && hist.length > 0) {
      e.preventDefault();
      if (historyIdx.current === -1) savedInput.current = input;
      const next = historyIdx.current === -1 ? hist.length - 1 : Math.max(0, historyIdx.current - 1);
      historyIdx.current = next;
      setInput(hist[next]);
    } else if (e.key === "ArrowDown" && historyIdx.current >= 0) {
      e.preventDefault();
      const next = historyIdx.current + 1;
      if (next >= hist.length) {
        historyIdx.current = -1;
        setInput(savedInput.current);
      } else {
        historyIdx.current = next;
        setInput(hist[next]);
      }
    }
  };

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { alert("10MB 이하만 가능합니다."); return; }
    const reader = new FileReader();
    reader.onload = () => setImageData(reader.result as string);
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  const clearHistory = async () => {
    await apiDelete(`/llm/history?session_id=${sessionId}`).catch(() => {});
    setMessages([]);
  };

  return (
    <div className="page-content llm-chat-page">
      <div className="card llm-chat-container">
        <div className="llm-chat-header">
          <h3 className="card-title">{_t("llm.title")}</h3>
          <div className="llm-chat-header-actions">
            {model && <span className="llm-model-badge">{model}</span>}
            <button className="btn btn-sm" onClick={clearHistory}>{_t("llm.clear")}</button>
          </div>
        </div>

        <div className="llm-chat-messages">
          {messages.length === 0 && (
            <div className="llm-chat-empty">
              <p>{_t("llm.emptyTitle")}</p>

              <div className="llm-tools-list">
                <h4>{_t("llm.availableTools")}</h4>
                <div className="llm-tools-grid">
                  <div className="llm-tool-item">
                    <span className="llm-tool-icon">📈</span>
                    <div><strong>{_t("llm.toolPrice")}</strong><br/><span className="text-secondary">{_t("llm.toolPriceDesc")}</span></div>
                  </div>
                  <div className="llm-tool-item">
                    <span className="llm-tool-icon">📊</span>
                    <div><strong>{_t("llm.toolBacktest")}</strong><br/><span className="text-secondary">{_t("llm.toolBacktestDesc")}</span></div>
                  </div>
                  <div className="llm-tool-item">
                    <span className="llm-tool-icon">🎯</span>
                    <div><strong>{_t("llm.toolSignal")}</strong><br/><span className="text-secondary">{_t("llm.toolSignalDesc")}</span></div>
                  </div>
                  <div className="llm-tool-item">
                    <span className="llm-tool-icon">📰</span>
                    <div><strong>{_t("llm.toolNews")}</strong><br/><span className="text-secondary">{_t("llm.toolNewsDesc")}</span></div>
                  </div>
                  <div className="llm-tool-item">
                    <span className="llm-tool-icon">🌐</span>
                    <div><strong>{_t("llm.toolWeb")}</strong><br/><span className="text-secondary">{_t("llm.toolWebDesc")}</span></div>
                  </div>
                  <div className="llm-tool-item">
                    <span className="llm-tool-icon">📎</span>
                    <div><strong>{_t("llm.toolImage")}</strong><br/><span className="text-secondary">{_t("llm.toolImageDesc")}</span></div>
                  </div>
                </div>
              </div>

              <div className="llm-suggestions">
                <h4>{_t("llm.tryAsking")}</h4>
                {[_t("llm.suggestion1"), _t("llm.suggestion2"), _t("llm.suggestion3"),
                  _t("llm.suggestion4"), _t("llm.suggestion5")].map((s, i) => (
                  <button key={i} className="btn btn-sm llm-suggestion-btn" onClick={() => { setInput(s); inputRef.current?.focus(); }}>
                    {s}
                  </button>
                ))}
              </div>

              <p className="llm-hint">{_t("llm.hint")}</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`llm-msg llm-msg-${msg.role}`}>
              <div className="llm-msg-sender">
                <div className="llm-msg-avatar">{msg.role === "user" ? "U" : "AI"}</div>
                <span className="llm-msg-name">
                  {msg.role === "user" ? _t("llm.you") : _t("llm.assistant")}
                </span>
              </div>
              <div className="llm-msg-bubble">
                {msg.image && (
                  <img src={msg.image} alt="attached" className="llm-msg-image" />
                )}
                {msg.role === "assistant" ? (
                  <MarkdownContent content={msg.content} />
                ) : (
                  <div className="llm-user-text">{msg.content}</div>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="llm-msg llm-msg-assistant">
              <div className="llm-msg-sender">
                <div className="llm-msg-avatar">AI</div>
                <span className="llm-msg-name">{_t("llm.assistant")}</span>
              </div>
              <div className="llm-msg-bubble llm-typing">
                <span /><span /><span />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="llm-chat-input-area">
          {imageData && (
            <div className="llm-image-preview">
              <img src={imageData} alt="preview" />
              <button className="llm-image-remove" onClick={() => setImageData(null)}>x</button>
            </div>
          )}
          <div className="llm-input-row">
            <button className="btn btn-sm llm-attach-btn" onClick={() => fileRef.current?.click()} disabled={loading} title={_t("llm.attachImage")}>
              📎
            </button>
            <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handleImageSelect} />
            <textarea
              ref={inputRef}
              className="llm-chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={_t("llm.placeholder")}
              rows={2}
              disabled={loading}
            />
            {loading ? (
              <button className="btn llm-stop-btn" onClick={stop}>
                {_t("llm.stop")}
              </button>
            ) : (
              <button className="btn btn-primary llm-send-btn" onClick={send} disabled={!input.trim() && !imageData}>
                {_t("llm.send")}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  const html = useMemo(() => {
    const raw = renderMarkdownWithLatex(content);
    return DOMPurify.sanitize(raw, {
      ADD_TAGS: ["semantics", "annotation", "math", "mrow", "mi", "mo", "mn", "msup", "mfrac", "msqrt", "mover", "munder", "mspace", "msub", "mtd", "mtr", "mtable", "mtext", "mpadded"],
      ADD_ATTR: ["xmlns", "mathvariant", "stretchy", "fence", "separator", "accent", "width", "height", "style"],
    });
  }, [content]);
  return <div className="llm-markdown" dangerouslySetInnerHTML={{ __html: html }} />;
}
