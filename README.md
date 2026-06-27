# Software Factory

> **SuperPlane Hackathon NYC, June 27 2026** — "Bash Script Funeral"

A SuperPlane app that takes a GitHub issue and runs it through an assembly line on the Canvas — an LLM agent writes a spec, a coding agent implements it, the GitHub integration opens a PR, the branch deploys to a Render preview environment, and the live link gets posted on the PR. **No human touches the code.**

## Architecture

```
GitHub Issue
     │
     ▼
[Get Issue]  ─── github.getIssue
     │
     ▼
[Generate Spec]  ─── claude.textPrompt (claude-sonnet-4-6)
     │
     ▼
[Validate Spec]  ─── filter (non-empty, >100 chars)
     │
     ▼
[Implement Code]  ─── HTTP POST → coding-service (FastAPI on Render)
     │                  └─ git clone → claude --dangerously-skip-permissions → commit & push
     ▼
[Validate Build]  ─── filter (success == true)
     │
     ▼
[Create Pull Request]  ─── github.createPullRequest
     │
     ▼
[Validate PR Exists]  ─── filter (PR number != null)
     │
     ▼
[Trigger Render Deploy]  ─── HTTP POST → coding-service /deploy
     │                         └─ Render API → poll until live
     ▼
[Validate Deploy Live]  ─── filter (status == "live")
     │
     ▼
[Post Preview Link]  ─── github.createIssueComment
```

## Components

| Directory | What it is |
|-----------|-----------|
| `canvas.yaml` | The SuperPlane pipeline definition |
| `coding_service/` | FastAPI service (Render) that runs Claude Code on cloned repos |
| `demo_app/` | React/Vite app showing the 5 validation issues as live UI |
| `render.yaml` | Render Blueprint — deploys both services |

## Validation Issues

The pipeline is validated against these 5 SuperPlane issues:

| # | Title | Status |
|---|-------|--------|
| #5368 | Markdown view mode (mermaid.js, @mention chips) | ✅ Demo |
| #5366 | Canvas version diff highlighting | ✅ Demo |
| #5164 | Send execution to agent chat | 🔄 Pipeline |
| #5704 | Run inspection UX paper cuts | ✅ Demo |
| #5705 | Canvas warnings improvements | 🔄 Pipeline |

## Render Track

Two Render services deployed via `render.yaml`:
1. **software-factory-coder** — the coding agent API (Standard plan)
2. **software-factory-demo** — the demo React app with PR Preview Environments enabled

## Setup

### Prerequisites
- SuperPlane Cloud org at [app.superplane.com](https://app.superplane.com)
- GitHub integration connected in SuperPlane
- Render account with API key

### Environment Variables (Render)
```
ANTHROPIC_API_KEY   # Claude API key
FACTORY_SECRET      # Shared secret between SuperPlane and the coding service
RENDER_API_KEY      # Render API key for deploy polling
RENDER_SERVICE_ID   # Render service ID of the demo app
```

### Deploy

```bash
# Install SuperPlane CLI
npm install -g @superplane/cli

# Login
superplane auth login

# Create the app and push the canvas
superplane apps create software-factory --canvas-file canvas.yaml

# Connect the GitHub integration in the SuperPlane UI
# Then run the pipeline by clicking "New Issue" → enter an issue number
```

### Deploy to Render

Connect this repo to Render and use the `render.yaml` blueprint, or:

```bash
# Via Render CLI
render deploy
```

## Demo Script (3 min)

1. Open SuperPlane Canvas — show the 10-node pipeline
2. Click "New Issue" → enter `5368` (markdown view)
3. Watch each stage light up: Get Issue → Generate Spec → Implement Code → PR → Deploy → Comment
4. Open the PR on GitHub — show the auto-generated code diff
5. Click the preview link — show the live demo app with markdown + mermaid rendering
6. **"No human wrote this code."**
