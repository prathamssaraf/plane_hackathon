/**
 * Issue #5368 — Markdown view mode with mermaid.js diagrams and @mention chips
 * Implements: toggle between edit/preview, mermaid rendering, @mention highlighting
 */
import { useState, useEffect, useRef } from "react";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "loose" });

const SAMPLE_CONTENT = `# Feature: Automated Deployment Pipeline

This doc describes the **Software Factory** architecture.

## Flow Diagram

\`\`\`mermaid
graph LR
  A[GitHub Issue] --> B[Spec Agent]
  B --> C{Valid?}
  C -- yes --> D[Code Agent]
  C -- no --> E[Error]
  D --> F[PR Created]
  F --> G[Render Deploy]
  G --> H[Preview Link]
\`\`\`

## Owners

Assigned to @pratham and @alex. Review requested from @superplane-team.

## Notes

- Each stage **validates** the previous one
- Uses \`claude-sonnet-4-6\` for spec + code generation
- Deployed via [Render](https://render.com) preview environments
`;

type Mode = "edit" | "preview";

interface MentionChipProps { name: string }
function MentionChip({ name }: MentionChipProps) {
  return (
    <span className="mention-chip" title={`@${name}`}>
      <span className="mention-avatar">{name[0].toUpperCase()}</span>
      @{name}
    </span>
  );
}

function renderTextWithMentions(text: string): React.ReactNode[] {
  const parts = text.split(/(@\w+)/g);
  return parts.map((part, i) =>
    part.startsWith("@") ? (
      <MentionChip key={i} name={part.slice(1)} />
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    mermaid
      .render(`mermaid-${Math.random().toString(36).slice(2)}`, code)
      .then(({ svg: rendered }) => {
        if (!cancelled) setSvg(rendered);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => { cancelled = true; };
  }, [code]);

  if (error) return <pre className="mermaid-error">{error}</pre>;
  if (!svg) return <div className="mermaid-loading">Rendering diagram…</div>;
  return (
    <div
      ref={ref}
      className="mermaid-diagram"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

function PreviewContent({ markdown }: { markdown: string }) {
  const lines = markdown.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Mermaid fence
    if (line.trim() === "```mermaid") {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && lines[i].trim() !== "```") {
        codeLines.push(lines[i]);
        i++;
      }
      blocks.push(<MermaidBlock key={i} code={codeLines.join("\n")} />);
      i++;
      continue;
    }

    // Code fence (non-mermaid)
    if (line.trim().startsWith("```")) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      blocks.push(<pre key={i} className="code-block"><code>{codeLines.join("\n")}</code></pre>);
      i++;
      continue;
    }

    // Headings
    const h3 = line.match(/^### (.+)/);
    const h2 = line.match(/^## (.+)/);
    const h1 = line.match(/^# (.+)/);
    if (h1) { blocks.push(<h1 key={i}>{renderTextWithMentions(h1[1])}</h1>); i++; continue; }
    if (h2) { blocks.push(<h2 key={i}>{renderTextWithMentions(h2[1])}</h2>); i++; continue; }
    if (h3) { blocks.push(<h3 key={i}>{renderTextWithMentions(h3[1])}</h3>); i++; continue; }

    // List items
    const listMatch = line.match(/^- (.+)/);
    if (listMatch) {
      const items: string[] = [];
      while (i < lines.length && lines[i].match(/^- /)) {
        items.push(lines[i].replace(/^- /, ""));
        i++;
      }
      blocks.push(
        <ul key={i}>
          {items.map((item, j) => (
            <li key={j}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>
      );
      continue;
    }

    // Paragraph
    if (line.trim()) {
      blocks.push(<p key={i}>{renderInlineMarkdown(line)}</p>);
    }
    i++;
  }

  return <div className="preview-content">{blocks}</div>;
}

function renderInlineMarkdown(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|@\w+)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i}>{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return <code key={i} className="inline-code">{part.slice(1, -1)}</code>;
        }
        if (part.startsWith("[") && part.includes("](")) {
          const [, label, url] = part.match(/\[([^\]]+)\]\(([^)]+)\)/) || [];
          return <a key={i} href={url} target="_blank" rel="noreferrer">{label}</a>;
        }
        if (part.startsWith("@")) {
          return <MentionChip key={i} name={part.slice(1)} />;
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

export default function MarkdownView() {
  const [mode, setMode] = useState<Mode>("edit");
  const [content, setContent] = useState(SAMPLE_CONTENT);

  return (
    <div className="markdown-view">
      <div className="md-toolbar">
        <h2>Markdown View Mode</h2>
        <div className="mode-toggle">
          <button
            className={`mode-btn${mode === "edit" ? " active" : ""}`}
            onClick={() => setMode("edit")}
          >
            ✏️ Edit
          </button>
          <button
            className={`mode-btn${mode === "preview" ? " active" : ""}`}
            onClick={() => setMode("preview")}
          >
            👁 Preview
          </button>
        </div>
      </div>

      <div className="md-body">
        {mode === "edit" ? (
          <textarea
            className="md-editor"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            spellCheck={false}
          />
        ) : (
          <PreviewContent markdown={content} />
        )}
      </div>

      <div className="md-hint">
        Try adding a <code>@mention</code> or a <code>```mermaid</code> block in edit mode, then switch to preview.
      </div>
    </div>
  );
}
