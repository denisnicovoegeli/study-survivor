// GraphView.jsx: Ansicht «LangGraph». Zeigt die Graphen chat und verarbeiten als Diagramm aus dem Code
// (GET /graphs, Mermaid), erklärt jeden Knoten, ordnet die Kursbausteine SW5 bis SW8 zu und spielt eine
// Frage live durch den Graphen chat (SSE-Events step und tool aus POST /chat).
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Loading } from "../ui/Loading.jsx";
import { renderMarkdown } from "../lib/markdown.js";
import { streamChat } from "../chat/sse.js";
import "./graph.css";

const { useState, useEffect, useRef, useCallback } = React;

const BEISPIELE = [
  "Welche Abgaben stehen in den nächsten zwei Wochen an?",
  "Was ist Reciprocal Rank Fusion?",
  "Schreib mir ein Gedicht über Katzen.",
];

const TABS = [
  { id: "chat", label: "Graph chat" },
  { id: "verarbeiten", label: "Graph verarbeiten" },
  { id: "bausteine", label: "Kursbausteine" },
];

function neuerThread() {
  return "graph-" + Math.random().toString(36).slice(2, 10);
}

// Mermaid wird erst geladen, wenn die Ansicht offen ist (eigener Chunk)
let mermaidPromise = null;
function loadMermaid() {
  if (!mermaidPromise) mermaidPromise = import("mermaid").then((m) => m.default);
  return mermaidPromise;
}

function cssVar(el, name, fallback) {
  const v = el ? getComputedStyle(el).getPropertyValue(name).trim() : "";
  return v || fallback;
}

// Knoten-ID aus der Mermaid-SVG: <g class="node" id="mermaid-x-flowchart-classify-3">
function nodeName(el) {
  const m = /flowchart-(.+)-\d+$/.exec(el.id || "");
  return m ? m[1] : null;
}

function CodeRef({ code }) {
  if (!code?.datei) return null;
  return (
    <code className="lg-code" title={`${code.datei}${code.zeile ? `:${code.zeile}` : ""}`}>
      {code.datei.replace(/^study_agent\//, "")}
      {code.zeile ? `:${code.zeile}` : ""}
    </code>
  );
}

function Diagramm({ id, source, dark, selected, onSelect, active, visited }) {
  const hostRef = useRef(null);
  const [error, setError] = useState(null);
  const [rendered, setRendered] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = await loadMermaid();
        const root = hostRef.current?.closest(".stu");
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: "base",
          fontFamily: "Manrope, sans-serif",
          themeVariables: {
            background: "transparent",
            primaryColor: cssVar(root, "--surface", "#fff"),
            primaryBorderColor: cssVar(root, "--line", "#ccc"),
            primaryTextColor: cssVar(root, "--fg", "#222"),
            lineColor: cssVar(root, "--muted", "#888"),
            edgeLabelBackground: cssVar(root, "--bg", "#fff"),
            fontSize: "14px",
          },
          flowchart: { curve: "basis", nodeSpacing: 36, rankSpacing: 44, htmlLabels: true },
        });
        const { svg } = await mermaid.render(`lg-${id}-${dark ? "d" : "l"}-${Date.now()}`, source);
        if (cancelled || !hostRef.current) return;
        hostRef.current.innerHTML = svg;
        setError(null);
        setRendered((n) => n + 1);
      } catch (e) {
        if (!cancelled) setError(e?.message || String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, source, dark]);

  // Klick auf Knoten und Hervorhebung nach jedem Render oder Zustandswechsel
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    const nodes = Array.from(host.querySelectorAll("g.node"));
    const handlers = [];
    for (const el of nodes) {
      const name = nodeName(el);
      if (!name) continue;
      const tech = name === "__start__" || name === "__end__";
      el.classList.toggle("is-tech", tech);
      el.classList.toggle("is-selected", name === selected);
      el.classList.toggle("is-active", name === active);
      el.classList.toggle("is-visited", visited.includes(name) && name !== active);
      if (!tech) {
        const h = () => onSelect(name === selected ? null : name);
        el.addEventListener("click", h);
        handlers.push([el, h]);
      }
    }
    return () => handlers.forEach(([el, h]) => el.removeEventListener("click", h));
  }, [rendered, selected, active, visited, onSelect]);

  return (
    <div className="lg-diagram">
      {error ? <div className="lg-error">Diagramm konnte nicht gezeichnet werden: {error}</div> : null}
      <div ref={hostRef} className="lg-svg" />
      {!rendered && !error ? <Loading text="Diagramm wird gezeichnet …" /> : null}
    </div>
  );
}

function KnotenKarte({ name, k, onClose }) {
  return (
    <div className="lg-card lg-node-card">
      <div className="lg-card-h">
        <span className="lg-node-name">{name}</span>
        <span className="lg-badge">{k.art}</span>
        {k.woche ? <span className="lg-badge lg-badge-acc">{k.woche}</span> : null}
        <button type="button" className="lg-x" onClick={onClose} aria-label="Karte schliessen">
          ×
        </button>
      </div>
      <p>{k.text}</p>
      <div className="lg-rw">
        <div>
          <div className="lg-label">liest</div>
          {k.liest.length ? k.liest.map((f) => <span key={f} className="lg-field">{f}</span>) : <span className="lg-muted">nichts</span>}
        </div>
        <div>
          <div className="lg-label">schreibt</div>
          {k.schreibt.map((f) => <span key={f} className="lg-field lg-field-w">{f}</span>)}
        </div>
      </div>
      <CodeRef code={k.code} />
    </div>
  );
}

function GraphInfo({ g }) {
  return (
    <div className="lg-card">
      <p className="lg-lead">{g.beschreibung}</p>
      <div className="lg-label">State</div>
      <dl className="lg-state">
        {g.state.map((s) => (
          <React.Fragment key={s.feld}>
            <dt>{s.feld}</dt>
            <dd>{s.text}</dd>
          </React.Fragment>
        ))}
      </dl>
      <div className="lg-label">Kanten mit Logik</div>
      <ul className="lg-list">
        {g.kanten.map((k) => <li key={k}>{k}</li>)}
      </ul>
      <div className="lg-hint">Klick auf einen Knoten im Diagramm zeigt, was er macht.</div>
      <CodeRef code={g.code} />
    </div>
  );
}

function LiveAblauf({ knoten, onActive, onVisited }) {
  const [frage, setFrage] = useState("");
  const [thread, setThread] = useState(neuerThread);
  const [busy, setBusy] = useState(false);
  const [schritte, setSchritte] = useState([]);
  const [ergebnis, setErgebnis] = useState(null);
  const [fehler, setFehler] = useState(null);

  const start = useCallback(
    async (text) => {
      const q = (text ?? frage).trim();
      if (!q || busy) return;
      setFrage(q);
      setBusy(true);
      setSchritte([]);
      setErgebnis(null);
      setFehler(null);
      onVisited(["__start__"]);
      onActive("__start__");
      const t0 = performance.now();
      try {
        await streamChat({ message: q, thread_id: thread }, (event, data) => {
          const ms = Math.round(performance.now() - t0);
          if (event === "step") {
            setSchritte((s) => [...s, { node: data.node, label: data.label, ms, tools: [] }]);
            onActive(data.node);
            onVisited((v) => [...v, data.node]);
          } else if (event === "tool") {
            setSchritte((s) => {
              const n = s.slice();
              if (n.length) n[n.length - 1] = { ...n[n.length - 1], tools: [...n[n.length - 1].tools, data] };
              return n;
            });
          } else if (event === "final") {
            setErgebnis({ ...data, ms });
            onActive("__end__");
            onVisited((v) => [...v, "__end__"]);
          } else if (event === "error") {
            setFehler(data.message);
          }
        });
      } catch (e) {
        setFehler(e.message);
      } finally {
        setBusy(false);
      }
    },
    [frage, busy, thread, onActive, onVisited]
  );

  return (
    <div className="lg-card lg-live">
      <div className="lg-card-h">
        <span className="lg-h3">Live-Ablauf</span>
        <span className="lg-muted lg-thread" title="thread_id dieser Demo">thread {thread}</span>
        <button
          type="button"
          className="lg-btn lg-btn-ghost"
          disabled={busy}
          onClick={() => {
            setThread(neuerThread());
            setSchritte([]);
            setErgebnis(null);
            onVisited([]);
            onActive(null);
          }}
          title="Neuer Thread: ohne Gedächtnis an frühere Fragen"
        >
          Neuer Thread
        </button>
      </div>
      <p className="lg-muted lg-small">
        Die Frage läuft durch den echten Graphen. Jeder Knoten leuchtet auf, sobald er fertig ist. Eine zweite Frage
        im selben Thread zeigt summarize und das Gedächtnis.
      </p>
      <form
        className="lg-ask"
        onSubmit={(e) => {
          e.preventDefault();
          start();
        }}
      >
        <input
          value={frage}
          onChange={(e) => setFrage(e.target.value)}
          placeholder="Frage an den Study Agent"
          disabled={busy}
        />
        <button type="submit" className="lg-btn" disabled={busy || !frage.trim()}>
          {busy ? "läuft …" : "Durchspielen"}
        </button>
      </form>
      <div className="lg-examples">
        {BEISPIELE.map((b) => (
          <button key={b} type="button" className="lg-chip" disabled={busy} onClick={() => start(b)}>
            {b}
          </button>
        ))}
      </div>

      {schritte.length ? (
        <ol className="lg-steps">
          {schritte.map((s, i) => (
            <li key={i} className={busy && i === schritte.length - 1 ? "is-now" : ""}>
              <span className="lg-step-node">{s.node}</span>
              <span className="lg-step-label">{s.label}</span>
              <span className="lg-step-ms">{(s.ms / 1000).toFixed(1)} s</span>
              {knoten[s.node]?.woche ? <span className="lg-badge lg-badge-acc">{knoten[s.node].woche}</span> : null}
              {s.node === "answer" && s.tools.length ? (
                <div className="lg-step-tools">
                  {s.tools.map((t, j) => (
                    <span key={j} className="lg-tool" title={JSON.stringify(t.args)}>
                      → {t.name}({Object.entries(t.args || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})
                    </span>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}

      {fehler ? <div className="lg-error">{fehler}</div> : null}

      {ergebnis ? (
        <div className="lg-result">
          <div className="lg-result-meta">
            <span className="lg-badge">{ergebnis.in_scope ? "zuständig" : "nicht zuständig"}</span>
            {ergebnis.category ? <span className="lg-badge">Kategorie: {ergebnis.category}</span> : null}
            {ergebnis.ergaenzung ? <span className="lg-badge lg-badge-warn">mit Ergänzung</span> : null}
            <span className="lg-muted">{(ergebnis.ms / 1000).toFixed(1)} s gesamt</span>
          </div>
          <div className="lg-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(ergebnis.answer || "") }} />
          {ergebnis.quellen?.length ? (
            <div className="lg-quellen">
              <div className="lg-label">Quellen</div>
              <ul>
                {ergebnis.quellen.map((q) => <li key={q}>{q}</li>)}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Freigaben({ api }) {
  const [liste, setListe] = useState(null);
  useEffect(() => {
    api("freigaben")
      .then((d) => setListe(d.freigaben || []))
      .catch(() => setListe([]));
  }, [api]);
  return (
    <div className="lg-card">
      <div className="lg-card-h">
        <span className="lg-h3">Human in the Loop: offene Freigaben</span>
      </div>
      <p className="lg-muted lg-small">
        Diese Threads stehen im Knoten freigabe still. Ihr Stand liegt im Checkpointer; der Entscheid im Chat-Panel
        setzt sie mit Command(resume=...) fort.
      </p>
      {liste === null ? (
        <Loading text="Freigaben werden geladen …" />
      ) : liste.length ? (
        <ul className="lg-freigaben">
          {liste.map((f) => (
            <li key={f.thread_id}>
              <span className="lg-file">{f.rel}</span>
              <span className="lg-muted">
                {f.runden} Runden, {f.beanstandungen?.length || 0} Beanstandungen
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="lg-muted lg-small">Keine offene Freigabe: alle Entwürfe kamen durch die Prüfung.</div>
      )}
    </div>
  );
}

function Bausteine({ data }) {
  return (
    <div className="lg-bausteine">
      <table className="lg-table">
        <thead>
          <tr>
            <th>Woche</th>
            <th>Baustein</th>
            <th>Umsetzung im Study Agent</th>
            <th>Code</th>
          </tr>
        </thead>
        <tbody>
          {data.bausteine.map((b, i) => (
            <tr key={i}>
              <td><span className="lg-badge lg-badge-acc">{b.woche}</span></td>
              <td>{b.baustein}</td>
              <td>{b.umsetzung}</td>
              <td><CodeRef code={b.code} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="lg-card">
        <div className="lg-h3">Bewusst weggelassen</div>
        <ul className="lg-list">
          {data.weggelassen.map((w) => (
            <li key={w.was}>
              <strong>{w.was}:</strong> {w.warum}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function GraphView() {
  const { api, dark } = useStudio();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("chat");
  const [selected, setSelected] = useState(null);
  const [active, setActive] = useState(null);
  const [visited, setVisited] = useState([]);

  useEffect(() => {
    api("graphs")
      .then(setData)
      .catch((e) => setError(e?.message || "Fehler beim Laden"));
  }, [api]);

  useEffect(() => {
    setSelected(null);
  }, [tab]);

  if (error) return <div className="lg"><div className="lg-error">{error}</div></div>;
  if (!data) return <div className="lg"><Loading text="Graphen werden geladen …" /></div>;

  const g = data.graphen.find((x) => x.id === tab);

  return (
    <div className="lg">
      <header className="lg-head">
        <div>
          <h1 className="lg-title">LangGraph im Study Agent</h1>
          <p className="lg-muted">
            Zwei Graphen, gebaut mit den Bausteinen aus SW5 bis SW8. Die Diagramme kommen direkt aus dem laufenden
            Code (get_graph().draw_mermaid()).
          </p>
        </div>
        <nav className="lg-tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              className={tab === t.id ? "is-on" : ""}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      {g ? (
        <>
          <div className="lg-sub">
            <span className="lg-h2">{g.titel}</span>
            <span className="lg-muted">{g.untertitel}</span>
          </div>
          <div className="lg-grid">
            <Diagramm
              id={g.id}
              source={g.mermaid}
              dark={dark}
              selected={selected}
              onSelect={setSelected}
              active={g.id === "chat" ? active : null}
              visited={g.id === "chat" ? visited : []}
            />
            <div className="lg-side">
              {selected && g.knoten[selected] ? (
                <KnotenKarte name={selected} k={g.knoten[selected]} onClose={() => setSelected(null)} />
              ) : (
                <GraphInfo g={g} />
              )}
            </div>
          </div>
          {g.id === "chat" ? (
            <LiveAblauf knoten={g.knoten} onActive={setActive} onVisited={setVisited} />
          ) : (
            <Freigaben api={api} />
          )}
        </>
      ) : (
        <Bausteine data={data} />
      )}
    </div>
  );
}

export default GraphView;
