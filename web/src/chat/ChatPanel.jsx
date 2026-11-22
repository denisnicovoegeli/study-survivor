// ChatPanel.jsx: Chat mit dem LangGraph-Agenten (SSE), Thread-Auswahl und Freigabe-Karten (interrupt)
import React from "react";
import { useStudio } from "../app/store.jsx";
import { api } from "../app/api.js";
import { Icon } from "../ui/Icon.jsx";
import { load, save } from "../ui/storage.js";
import { renderMarkdown } from "../lib/markdown.js";
import { streamChat } from "./sse.js";
import "./chat.css";

const { useState, useEffect, useRef, useCallback } = React;

function newThreadId() {
  return "t-" + Math.random().toString(36).slice(2, 10);
}

function Message({ m }) {
  if (m.role === "user") {
    return <div className="cp-msg cp-user">{m.text}</div>;
  }
  return (
    <div className="cp-msg cp-bot">
      {m.steps?.length > 0 && !m.done && (
        <div className="cp-steps">
          {m.steps.map((s, i) => (
            <span key={i} className={i === m.steps.length - 1 ? "is-now" : ""}>{s}</span>
          ))}
        </div>
      )}
      {m.tools?.length > 0 && (
        <div className="cp-tools">
          {m.tools.map((t, i) => (
            <span key={i} className="cp-tool" title={JSON.stringify(t.args)}>🔧 {t.name}</span>
          ))}
        </div>
      )}
      {m.text ? (
        <div className="cp-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }} />
      ) : !m.done ? (
        <div className="cp-wait">denkt nach …</div>
      ) : null}
      {m.error && <div className="cp-error">{m.error}</div>}
      {m.quellen?.length > 0 && (
        <div className="cp-quellen">
          <div className="cp-quellen-title">Quellen</div>
          <ul>{m.quellen.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </div>
      )}
      {m.done && m.meta && (
        <div className="cp-meta">
          {m.meta.category} · {m.meta.in_scope ? "zuständig" : "nicht zuständig"}
          {m.meta.ergaenzung ? " · enthält Ergänzungen" : ""}
        </div>
      )}
    </div>
  );
}

export function FreigabeCard({ f, onDone }) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [result, setResult] = useState(null);
  const name = f.rel.split("/").pop();

  const decide = async (decision) => {
    setBusy(true);
    try {
      const r = await api(`freigaben/${encodeURIComponent(f.thread_id)}`, {
        method: "POST",
        body: { decision, feedback },
      });
      setResult(r);
      onDone?.();
    } catch (e) {
      setResult({ error: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cp-freigabe">
      <div className="cp-freigabe-head">
        <Icon n="lock" /> Freigabe nötig: <b title={f.rel}>{name}</b>
      </div>
      <div className="cp-freigabe-sub">
        Der Prüfer ({f.runden} Runden) lehnt den Entwurf noch ab:
      </div>
      <ul className="cp-beanstandungen">
        {f.beanstandungen.map((b, i) => (
          <li key={i}>
            <span className={"cp-art cp-art-" + b.art}>{b.art}</span>
            {b.folie ? ` Folie ${b.folie}: ` : " "}
            {b.beschreibung}
          </li>
        ))}
      </ul>
      <div className="cp-freigabe-sub">
        Entwurf: {f.entwurf?.folien}/{f.entwurf?.seiten} Folien, {f.entwurf?.termine?.length || 0} Termine
      </div>
      {result ? (
        <div className={result.error ? "cp-error" : "cp-ok"}>
          {result.error || `Entscheid: ${result.entscheid}${result.offen ? " (erneut in Freigabe)" : ""}`}
        </div>
      ) : (
        <>
          <textarea
            className="cp-feedback"
            placeholder="Feedback für „Bearbeiten“ (optional)"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={2}
          />
          <div className="cp-freigabe-actions">
            <button disabled={busy} className="cp-btn cp-btn-ok" onClick={() => decide("approve")}>Freigeben</button>
            <button disabled={busy || !feedback.trim()} className="cp-btn" onClick={() => decide("edit")}>Bearbeiten</button>
            <button disabled={busy} className="cp-btn cp-btn-no" onClick={() => decide("reject")}>Ablehnen</button>
          </div>
        </>
      )}
    </div>
  );
}

export function ChatPanel() {
  const { chatRequest, clearChatRequest, chatContext } = useStudio();
  const [threadId, setThreadId] = useState(() => load("chat-thread", null) || newThreadId());
  const [threads, setThreads] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [freigaben, setFreigaben] = useState([]);
  const listRef = useRef(null);

  const refreshThreads = useCallback(() => {
    api("chat/threads").then((d) => setThreads(d.threads || [])).catch(() => {});
  }, []);
  const refreshFreigaben = useCallback(() => {
    api("freigaben").then((d) => setFreigaben(d.freigaben || [])).catch(() => {});
  }, []);

  useEffect(() => {
    save("chat-thread", threadId);
    api(`chat/history?thread_id=${encodeURIComponent(threadId)}`)
      .then((d) => setMessages((d.messages || []).map((m) => ({ ...m, done: true }))))
      .catch(() => setMessages([]));
  }, [threadId]);

  useEffect(() => {
    refreshThreads();
    refreshFreigaben();
  }, [refreshThreads, refreshFreigaben]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, freigaben]);

  const send = useCallback(
    async (text) => {
      const frage = (text ?? input).trim();
      if (!frage || busy) return;
      setInput("");
      setBusy(true);
      setMessages((prev) => [...prev, { role: "user", text: frage }, { role: "assistant", text: "", steps: [], tools: [] }]);
      const patch = (fn) =>
        setMessages((prev) => {
          const next = prev.slice();
          next[next.length - 1] = fn({ ...next[next.length - 1] });
          return next;
        });
      try {
        await streamChat({ message: frage, thread_id: threadId, context: chatContext }, (event, data) => {
          if (event === "step") patch((m) => ({ ...m, steps: [...m.steps, data.label] }));
          else if (event === "tool") patch((m) => ({ ...m, tools: [...m.tools, data] }));
          else if (event === "token") patch((m) => ({ ...m, text: m.text + data.text }));
          else if (event === "final")
            patch((m) => ({
              ...m,
              text: data.answer,
              quellen: data.quellen,
              done: true,
              meta: { category: data.category, in_scope: data.in_scope, ergaenzung: data.ergaenzung },
            }));
          else if (event === "error") patch((m) => ({ ...m, error: data.message, done: true }));
        });
      } catch (e) {
        patch((m) => ({ ...m, error: e.message, done: true }));
      } finally {
        setBusy(false);
        refreshThreads();
      }
    },
    [input, busy, threadId, chatContext, refreshThreads]
  );

  // Anfragen aus Suche, Übersicht und Dokument (sendToChat)
  useEffect(() => {
    if (chatRequest?.text) {
      send(chatRequest.text);
      clearChatRequest();
    }
  }, [chatRequest, clearChatRequest, send]);

  return (
    <div className="cp">
      <div className="cp-head">
        <Icon n="chat" />
        <select value={threadId} onChange={(e) => setThreadId(e.target.value)} title="Gespräch wählen">
          {!threads.some((t) => t.thread_id === threadId) && <option value={threadId}>Neues Gespräch</option>}
          {threads.map((t) => (
            <option key={t.thread_id} value={t.thread_id}>{t.title || t.thread_id}</option>
          ))}
        </select>
        <button className="cp-icon" title="Neues Gespräch" onClick={() => setThreadId(newThreadId())}>
          <Icon n="plus" />
        </button>
      </div>

      <div className="cp-list" ref={listRef}>
        {freigaben.map((f) => (
          <FreigabeCard key={f.thread_id} f={f} onDone={() => setTimeout(refreshFreigaben, 8000)} />
        ))}
        {messages.length === 0 && (
          <div className="cp-empty">
            Frag nach Terminen, Kursinhalten oder Prüfungen. Der Agent antwortet aus dem Kursmaterial und nennt die Quellen.
          </div>
        )}
        {messages.map((m, i) => <Message key={i} m={m} />)}
      </div>

      <form
        className="cp-input"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <textarea
          value={input}
          placeholder="Frage zum Studium …"
          rows={2}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button type="submit" className="cp-send" disabled={busy || !input.trim()} title="Senden">
          <Icon n="send" />
        </button>
      </form>
    </div>
  );
}

export default ChatPanel;
