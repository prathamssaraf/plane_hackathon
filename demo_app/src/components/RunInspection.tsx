/**
 * Issue #5704 — Run inspection UX paper cuts
 * Shows run timeline, payload inspector, and step drill-down
 */
import { useState } from "react";

const MOCK_RUN = {
  id: "run-8f3k2m",
  status: "completed",
  startedAt: "2026-06-27T14:22:00Z",
  finishedAt: "2026-06-27T14:28:47Z",
  trigger: "Manual Run",
  steps: [
    {
      id: "step-1",
      name: "Get Issue",
      component: "github.getIssue",
      status: "success",
      durationMs: 421,
      payload: {
        number: 5368,
        title: "Add markdown view mode with mermaid.js support",
        state: "open",
        body: "Users need a way to preview markdown content with mermaid diagrams...",
      },
    },
    {
      id: "step-2",
      name: "Generate Spec",
      component: "claude.textPrompt",
      status: "success",
      durationMs: 4820,
      payload: {
        text: '{"title":"Markdown view mode","summary":"Add edit/preview toggle with mermaid rendering and @mention chips","files_to_modify":["src/components/MarkdownView.tsx"],"implementation_steps":["Add mode toggle button","Integrate mermaid.js","Parse @mention syntax"],"branch_name":"feature/issue-5368-markdown-view"}',
        model: "claude-sonnet-4-6",
        usage: { input_tokens: 512, output_tokens: 187 },
      },
    },
    {
      id: "step-3",
      name: "Validate Spec",
      component: "filter",
      status: "success",
      durationMs: 12,
      payload: { passed: true, condition_value: true },
    },
    {
      id: "step-4",
      name: "Implement Code",
      component: "http",
      status: "success",
      durationMs: 92340,
      payload: {
        success: true,
        branch: "feature/issue-5368-markdown-view",
        commit_sha: "a3f8c21d",
        files_changed: "- `src/components/MarkdownView.tsx`\n- `src/App.css`",
      },
    },
    {
      id: "step-5",
      name: "Create Pull Request",
      component: "github.createPullRequest",
      status: "success",
      durationMs: 683,
      payload: {
        number: 47,
        html_url: "https://github.com/superplanehq/demo/pull/47",
        state: "open",
        title: "feat(#5368): Add markdown view mode with mermaid.js support",
      },
    },
    {
      id: "step-6",
      name: "Trigger Render Deploy",
      component: "http",
      status: "success",
      durationMs: 187450,
      payload: {
        success: true,
        preview_url: "https://software-factory-demo-pr-47.onrender.com",
        status: "live",
        build_duration_s: 187,
      },
    },
    {
      id: "step-7",
      name: "Post Preview Link",
      component: "github.createIssueComment",
      status: "success",
      durationMs: 341,
      payload: {
        id: 2041829,
        html_url: "https://github.com/superplanehq/demo/issues/5368#issuecomment-2041829",
      },
    },
  ],
};

const STATUS_COLORS: Record<string, string> = {
  success: "#22c55e",
  failed: "#ef4444",
  running: "#3b82f6",
  pending: "#94a3b8",
};

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

export default function RunInspection() {
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const step = MOCK_RUN.steps.find((s) => s.id === selectedStep);

  const totalMs = MOCK_RUN.steps.reduce((sum, s) => sum + s.durationMs, 0);

  return (
    <div className="run-inspection">
      <div className="run-header">
        <div>
          <h2>Run Inspection</h2>
          <span className="run-id">#{MOCK_RUN.id}</span>
        </div>
        <div className="run-meta">
          <span className="run-status" style={{ color: STATUS_COLORS.success }}>
            ✓ Completed
          </span>
          <span className="run-duration">{formatDuration(totalMs)}</span>
        </div>
      </div>

      {/* Timeline */}
      <div className="timeline">
        {MOCK_RUN.steps.map((s, idx) => {
          const widthPct = (s.durationMs / totalMs) * 100;
          return (
            <div
              key={s.id}
              className={`timeline-row${selectedStep === s.id ? " selected" : ""}`}
              onClick={() => setSelectedStep(selectedStep === s.id ? null : s.id)}
            >
              <div className="timeline-label">
                <span className="step-num">{idx + 1}</span>
                <span className="step-name">{s.name}</span>
                <span className="step-component">{s.component}</span>
              </div>
              <div className="timeline-bar-wrap">
                <div
                  className="timeline-bar"
                  style={{
                    width: `${Math.max(widthPct, 0.5)}%`,
                    background: STATUS_COLORS[s.status],
                  }}
                  title={formatDuration(s.durationMs)}
                />
                <span className="timeline-dur">{formatDuration(s.durationMs)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Payload inspector */}
      {step && (
        <div className="payload-inspector">
          <div className="payload-header">
            <span className="payload-title">
              {step.name} — output payload
            </span>
            <button className="close-btn" onClick={() => setSelectedStep(null)}>
              ✕
            </button>
          </div>
          <pre className="payload-json">
            {JSON.stringify(step.payload, null, 2)}
          </pre>
        </div>
      )}

      {!selectedStep && (
        <div className="run-hint">
          Click a step in the timeline to inspect its output payload.
        </div>
      )}
    </div>
  );
}
