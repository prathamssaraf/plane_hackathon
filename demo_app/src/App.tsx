import { useState } from "react";
import MarkdownView from "./components/MarkdownView";
import CanvasDiff from "./components/CanvasDiff";
import RunInspection from "./components/RunInspection";
import "./App.css";

const TABS = [
  { id: "markdown", label: "Markdown View (#5368)" },
  { id: "canvas-diff", label: "Canvas Diff (#5366)" },
  { id: "run-inspection", label: "Run Inspection (#5704)" },
];

export default function App() {
  const [tab, setTab] = useState("markdown");

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <span className="logo">⚙️ Software Factory</span>
          <span className="subtitle">SuperPlane Hackathon Demo — auto-generated PoC</span>
        </div>
      </header>
      <nav className="tab-bar">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab-btn${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <main className="tab-content">
        {tab === "markdown" && <MarkdownView />}
        {tab === "canvas-diff" && <CanvasDiff />}
        {tab === "run-inspection" && <RunInspection />}
      </main>
    </div>
  );
}
