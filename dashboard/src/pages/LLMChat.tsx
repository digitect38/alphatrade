import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { marked } from "marked";
import katex from "katex";
import "katex/dist/katex.min.css";
import DOMPurify from "dompurify";
import { apiGet, apiPost, apiDelete } from "../hooks/useApi";

// Configure marked for safe, compact output
marked.setOptions({
  breaks: true,
  gfm: true,
});

/**
 * Render LaTeX expressions in HTML string.
 * Supports:
 *   $$...$$ or \[...\]  → display math (block)
 *   $...$  or \(...\)   → inline math
 */
function renderLatex(html: string): string {
  // Display math: $$...$$ or \[...\]
  html = html.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => {
    try { return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }); }
    catch { return `<code>${tex}</code>`; }
  });
  html = html.replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => {
    try { return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }); }
    catch { return `<code>${tex}</code>`; }
  });
  // Inline math: $...$ or \(...\)  — avoid matching $$
  html = html.replace(/(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)/g, (_, tex) => {
    try { return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }); }
    catch { return `<code>${tex}</code>`; }
  });
  html = html.replace(/\\\((.+?)\\\)/g, (_, tex) => {
    try { return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }); }
    catch { return `<code>${tex}</code>`; }
  });
  return html;
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  ts?: string;
}

export default function LLMChatPage({ t: _t }: { t: (k: string) => string }) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [model, setModel] = useState("");
  const [sessionId] = useState(() => `web-${Date.now()}`);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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
    if (!text || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);
    try {
      const res = await apiPost<{ reply: string; model: string }>("/llm/chat", {
        message: text,
        session_id: sessionId,
      });
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
      if (res.model) setModel(res.model);
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${e.message}` },
      ]);
    }
    setLoading(false);
    inputRef.current?.focus();
  }, [input, loading, sessionId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
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
              <div className="llm-suggestions">
                {[_t("llm.suggestion1"), _t("llm.suggestion2"), _t("llm.suggestion3")].map((s, i) => (
                  <button key={i} className="btn btn-sm llm-suggestion-btn" onClick={() => { setInput(s); inputRef.current?.focus(); }}>
                    {s}
                  </button>
                ))}
              </div>
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
          <button className="btn btn-primary llm-send-btn" onClick={send} disabled={loading || !input.trim()}>
            {_t("llm.send")}
          </button>
        </div>
      </div>
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  const html = useMemo(() => {
    const raw = renderLatex(marked.parse(content) as string);
    return DOMPurify.sanitize(raw, { ADD_TAGS: ["semantics", "annotation", "math", "mrow", "mi", "mo", "mn", "msup", "mfrac", "msqrt", "mover", "munder"], ADD_ATTR: ["xmlns", "mathvariant", "stretchy", "fence", "separator", "accent"] });
  }, [content]);
  return <div className="llm-markdown" dangerouslySetInnerHTML={{ __html: html }} />;
}
