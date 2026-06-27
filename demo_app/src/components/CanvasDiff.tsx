/**
 * Issue #5366 — Canvas version diff highlighting
 * Shows a before/after diff of a canvas.yaml with inline highlights
 */

const BEFORE_YAML = `apiVersion: v1
kind: Canvas
metadata:
  name: deploy-pipeline
spec:
  nodes:
    - id: trigger-push
      name: On Push
      type: TYPE_TRIGGER
      component: github.onPush
    - id: run-tests
      name: Run Tests
      type: TYPE_ACTION
      component: http
      configuration:
        method: POST
        url: https://ci.example.com/run
    - id: deploy
      name: Deploy
      type: TYPE_ACTION
      component: http
      configuration:
        method: POST
        url: https://deploy.example.com
  edges:
    - sourceId: trigger-push
      targetId: run-tests
      channel: default
    - sourceId: run-tests
      targetId: deploy
      channel: default`;

const AFTER_YAML = `apiVersion: v1
kind: Canvas
metadata:
  name: deploy-pipeline
spec:
  nodes:
    - id: trigger-push
      name: On Push
      type: TYPE_TRIGGER
      component: github.onPush
    - id: run-tests
      name: Run Tests
      type: TYPE_ACTION
      component: http
      configuration:
        method: POST
        url: https://ci.example.com/run
        timeout: 120000
    - id: validate-tests
      name: Validate Tests
      type: TYPE_ACTION
      component: filter
      configuration:
        condition: $["Run Tests"].data.body.passed == true
    - id: deploy
      name: Deploy
      type: TYPE_ACTION
      component: http
      configuration:
        method: POST
        url: https://deploy.example.com
        headers:
          X-Env: production
  edges:
    - sourceId: trigger-push
      targetId: run-tests
      channel: default
    - sourceId: run-tests
      targetId: validate-tests
      channel: default
    - sourceId: validate-tests
      targetId: deploy
      channel: default`;

type DiffLine = {
  type: "same" | "added" | "removed";
  content: string;
};

function computeDiff(before: string, after: string): DiffLine[] {
  const beforeLines = before.split("\n");
  const afterLines = after.split("\n");

  const result: DiffLine[] = [];
  let bi = 0;
  let ai = 0;

  while (bi < beforeLines.length || ai < afterLines.length) {
    const bl = beforeLines[bi];
    const al = afterLines[ai];

    if (bi >= beforeLines.length) {
      result.push({ type: "added", content: al });
      ai++;
    } else if (ai >= afterLines.length) {
      result.push({ type: "removed", content: bl });
      bi++;
    } else if (bl === al) {
      result.push({ type: "same", content: bl });
      bi++;
      ai++;
    } else {
      // Simple heuristic: look ahead a few lines to find a match
      const lookahead = 4;
      let matched = false;
      for (let d = 1; d <= lookahead; d++) {
        if (ai + d < afterLines.length && afterLines[ai + d] === bl) {
          for (let k = 0; k < d; k++) {
            result.push({ type: "added", content: afterLines[ai + k] });
          }
          ai += d;
          matched = true;
          break;
        }
        if (bi + d < beforeLines.length && beforeLines[bi + d] === al) {
          for (let k = 0; k < d; k++) {
            result.push({ type: "removed", content: beforeLines[bi + k] });
          }
          bi += d;
          matched = true;
          break;
        }
      }
      if (!matched) {
        result.push({ type: "removed", content: bl });
        result.push({ type: "added", content: al });
        bi++;
        ai++;
      }
    }
  }

  return result;
}

export default function CanvasDiff() {
  const diff = computeDiff(BEFORE_YAML, AFTER_YAML);
  const added = diff.filter((l) => l.type === "added").length;
  const removed = diff.filter((l) => l.type === "removed").length;

  return (
    <div className="canvas-diff">
      <div className="diff-header">
        <h2>Canvas Version Diff</h2>
        <div className="diff-stats">
          <span className="stat added">+{added} added</span>
          <span className="stat removed">−{removed} removed</span>
        </div>
      </div>

      <div className="diff-legend">
        <span className="legend-item added-bg">Added lines</span>
        <span className="legend-item removed-bg">Removed lines</span>
        <span className="legend-item same-bg">Unchanged</span>
      </div>

      <div className="diff-view">
        <div className="diff-label">
          <span>v1 (before)</span>
          <span>v2 (after)</span>
        </div>
        <div className="diff-lines">
          {diff.map((line, i) => (
            <div key={i} className={`diff-line ${line.type}`}>
              <span className="diff-gutter">
                {line.type === "added" ? "+" : line.type === "removed" ? "−" : " "}
              </span>
              <code className="diff-code">{line.content}</code>
            </div>
          ))}
        </div>
      </div>

      <div className="diff-summary">
        This diff was generated automatically by the Software Factory pipeline when
        comparing the canvas.yaml before and after implementing issue #5366.
      </div>
    </div>
  );
}
