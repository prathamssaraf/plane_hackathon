"""
Software Factory — Coding Service
Clones a repo, creates a branch, runs Claude Code with the spec,
commits and pushes, then optionally triggers a Render preview deploy.
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Software Factory — Coding Service", version="1.0.0")

FACTORY_SECRET = os.environ.get("FACTORY_SECRET", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "")
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "")


# ── Request / Response models ─────────────────────────────────────────────────

class Spec(BaseModel):
    title: str
    summary: str
    files_to_modify: list[str]
    implementation_steps: list[str]
    acceptance_criteria: list[str]
    branch_name: str


class ImplementRequest(BaseModel):
    repo: str                # "owner/name"
    issue_number: str
    base_branch: str = "main"
    spec: Spec | dict        # accept raw dict too
    github_token: str


class DeployRequest(BaseModel):
    repo: str
    branch: str
    pr_number: str


# ── Auth helper ───────────────────────────────────────────────────────────────

def require_auth(x_factory_secret: str = Header(default="")):
    if FACTORY_SECRET and x_factory_secret != FACTORY_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Git helpers ───────────────────────────────────────────────────────────────

@contextmanager
def cloned_repo(repo: str, github_token: str, base_branch: str):
    with tempfile.TemporaryDirectory(prefix="factory-") as tmpdir:
        clone_url = f"https://x-access-token:{github_token}@github.com/{repo}.git"
        _run(["git", "clone", "--depth", "50", "--branch", base_branch, clone_url, tmpdir])
        _run(["git", "config", "user.email", "factory@superplane.com"], cwd=tmpdir)
        _run(["git", "config", "user.name", "Software Factory"], cwd=tmpdir)
        yield tmpdir


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    log.info("$ %s", " ".join(cmd))
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        log.error("STDOUT: %s", result.stdout[-2000:])
        log.error("STDERR: %s", result.stderr[-2000:])
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr[-500:]}")
    return result


# ── Claude Code runner ────────────────────────────────────────────────────────

def build_task_prompt(spec: dict, repo: str, issue_number: str) -> str:
    steps = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(spec.get("implementation_steps", [])))
    criteria = "\n".join(f"  - {c}" for c in spec.get("acceptance_criteria", []))
    files = ", ".join(spec.get("files_to_modify", []))
    return f"""You are implementing a GitHub issue in the {repo} repository.

## Task
{spec.get("title", "")}

## Summary
{spec.get("summary", "")}

## Implementation Steps
{steps}

## Files most likely to need changes
{files}

## Acceptance Criteria
{criteria}

## Instructions
- Implement ALL steps above.
- Modify only what is needed.
- Keep changes focused and minimal.
- Do not add tests unless explicitly listed in the steps.
- Commit your changes with a clear message referencing issue #{issue_number}.
- After implementing, run any available type-check or build command to verify the change compiles.
"""


def run_claude_code(task: str, cwd: str) -> dict:
    """Run Claude Code CLI non-interactively."""
    env = {**os.environ, "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY}

    # claude is installed globally via npm i -g @anthropic-ai/claude-code
    result = subprocess.run(
        [
            "claude",
            "--dangerously-skip-permissions",
            "--model", "claude-sonnet-4-6",
            "-p", task,
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=480,
    )
    log.info("Claude exit code: %d", result.returncode)
    log.info("Claude stdout (tail): %s", result.stdout[-3000:])
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Claude Code failed: {result.stderr[-500:]}")
    return {
        "stdout": result.stdout,
        "exit_code": result.returncode,
    }


def get_changed_files(cwd: str) -> list[str]:
    result = _run(["git", "diff", "--name-only", "HEAD"], cwd=cwd)
    staged = _run(["git", "diff", "--cached", "--name-only"], cwd=cwd)
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], cwd=cwd)
    files = set(
        (result.stdout + staged.stdout + untracked.stdout).strip().splitlines()
    )
    return [f for f in files if f]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/implement")
def implement(req: ImplementRequest, x_factory_secret: str = Header(default="")):
    require_auth(x_factory_secret)

    spec = req.spec if isinstance(req.spec, dict) else req.spec.model_dump()
    branch = re.sub(r"[^a-zA-Z0-9/_-]", "-", spec.get("branch_name", f"feature/issue-{req.issue_number}"))
    branch = branch[:80]

    log.info("Starting implementation: repo=%s issue=%s branch=%s", req.repo, req.issue_number, branch)

    try:
        with cloned_repo(req.repo, req.github_token, req.base_branch) as tmpdir:
            # Create feature branch
            _run(["git", "checkout", "-b", branch], cwd=tmpdir)

            # Build and run the coding task
            task = build_task_prompt(spec, req.repo, req.issue_number)
            claude_result = run_claude_code(task, tmpdir)

            # Collect changed files
            changed = get_changed_files(tmpdir)
            log.info("Changed files: %s", changed)

            if not changed:
                log.warning("Claude Code made no file changes — attempting anyway")

            # Stage and commit everything
            _run(["git", "add", "-A"], cwd=tmpdir)

            commit_msg = (
                f"feat: implement #{req.issue_number} — {spec.get('title', 'auto implementation')}\n\n"
                f"Closes #{req.issue_number}\n"
                f"Generated by Software Factory on SuperPlane."
            )
            try:
                _run(["git", "commit", "-m", commit_msg], cwd=tmpdir)
            except RuntimeError:
                # Nothing to commit is OK if Claude had nothing to change
                log.warning("git commit failed (possibly nothing to commit)")

            # Push to origin
            _run(["git", "push", "origin", branch, "--force-with-lease"], cwd=tmpdir)

            commit_sha = _run(["git", "rev-parse", "HEAD"], cwd=tmpdir).stdout.strip()

            return {
                "success": True,
                "branch": branch,
                "commit_sha": commit_sha,
                "files_changed": "\n".join(f"- `{f}`" for f in changed) if changed else "_no files changed_",
                "spec_summary": spec.get("summary", ""),
                "acceptance_criteria": "\n".join(f"- [ ] {c}" for c in spec.get("acceptance_criteria", [])),
                "claude_output_tail": claude_result["stdout"][-500:],
            }

    except Exception as exc:
        log.exception("Implementation failed")
        return {
            "success": False,
            "error": str(exc),
            "branch": branch,
        }


@app.post("/deploy")
def deploy(req: DeployRequest, x_factory_secret: str = Header(default="")):
    """
    Trigger a Render deploy for the branch and poll until it's live.
    Render automatically creates preview envs for PRs if configured.
    Here we also support the deploy hook approach.
    """
    require_auth(x_factory_secret)

    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        return {
            "success": False,
            "error": "RENDER_API_KEY or RENDER_SERVICE_ID not set",
            "preview_url": None,
            "status": "skipped",
        }

    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}",
        "Content-Type": "application/json",
    }

    start = time.time()

    # Trigger deploy
    log.info("Triggering Render deploy for branch=%s", req.branch)
    resp = httpx.post(
        f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys",
        headers=headers,
        json={"clearCache": False},
        timeout=30,
    )
    resp.raise_for_status()
    deploy_data = resp.json()
    deploy_id = deploy_data.get("deploy", {}).get("id") or deploy_data.get("id")
    log.info("Deploy triggered: %s", deploy_id)

    # Poll until live (max 10 minutes)
    preview_url = None
    status = "pending"
    for attempt in range(40):
        time.sleep(15)
        try:
            poll = httpx.get(
                f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys/{deploy_id}",
                headers=headers,
                timeout=15,
            )
            poll.raise_for_status()
            poll_data = poll.json()
            status = poll_data.get("status", "pending")
            log.info("Deploy status [%d]: %s", attempt, status)

            if status == "live":
                # Get the service URL
                svc = httpx.get(
                    f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}",
                    headers=headers,
                    timeout=15,
                )
                svc.raise_for_status()
                preview_url = svc.json().get("serviceDetails", {}).get("url")
                break

            if status in ("failed", "canceled", "deactivated"):
                break

        except Exception as e:
            log.warning("Poll error: %s", e)
            continue

    build_duration_s = int(time.time() - start)

    return {
        "success": status == "live",
        "preview_url": preview_url,
        "status": status,
        "deploy_id": deploy_id,
        "build_duration_s": build_duration_s,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=False)
