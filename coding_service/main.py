"""
Software Factory — Coding Service
Uses K2-Think (OpenAI-compatible reasoning model) to implement GitHub issues.
"""

import logging
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Header
from openai import OpenAI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Software Factory — Coding Service", version="1.0.0")

FACTORY_SECRET = os.environ.get("FACTORY_SECRET", "")
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "")
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "")

K2_API_KEY = os.environ.get("K2_API_KEY", "")
K2_BASE_URL = os.environ.get("K2_BASE_URL", "https://api.k2think.ai/v1")
K2_MODEL = os.environ.get("K2_MODEL", "MBZUAI-IFM/K2-Think-v2")

# K2 sits behind Cloudflare — must send a non-Python user-agent
k2_client = OpenAI(
    api_key=K2_API_KEY,
    base_url=K2_BASE_URL,
    default_headers={"User-Agent": "OpenAI/Python 1.0"},
)


# ── Models ────────────────────────────────────────────────────────────────────

class Spec(BaseModel):
    title: str
    summary: str
    files_to_modify: list[str]
    implementation_steps: list[str]
    acceptance_criteria: list[str]
    branch_name: str


class ImplementRequest(BaseModel):
    repo: str
    issue_number: str
    base_branch: str = "main"
    spec: dict
    github_token: str


class DeployRequest(BaseModel):
    repo: str
    branch: str
    pr_number: str


# ── Auth ──────────────────────────────────────────────────────────────────────

def check_auth(secret: str):
    if FACTORY_SECRET and secret != FACTORY_SECRET:
        from fastapi import HTTPException
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
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        log.error("STDERR: %s", r.stderr[-2000:])
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{r.stderr[-400:]}")
    return r


def get_repo_tree(cwd: str, max_files: int = 80) -> str:
    r = subprocess.run(
        ["git", "ls-files"],
        cwd=cwd, capture_output=True, text=True, timeout=30
    )
    lines = r.stdout.strip().splitlines()[:max_files]
    return "\n".join(lines)


def read_relevant_files(cwd: str, file_paths: list[str]) -> str:
    out = []
    for path in file_paths[:8]:  # cap at 8 files
        full = os.path.join(cwd, path)
        if os.path.exists(full):
            try:
                content = open(full).read()[:4000]  # cap per file
                out.append(f"=== {path} ===\n{content}")
            except Exception:
                pass
    return "\n\n".join(out)


# ── K2-Think LLM helper ───────────────────────────────────────────────────────

def strip_reasoning(text: str) -> str:
    """K2-Think wraps its chain-of-thought in <think>...</think> — strip it."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


def k2_complete(system: str, user: str, max_tokens: int = 8192) -> str:
    log.info("Calling K2-Think (max_tokens=%d)", max_tokens)
    resp = k2_client.chat.completions.create(
        model=K2_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    raw = resp.choices[0].message.content or ""
    return strip_reasoning(raw)


# ── Code implementation ───────────────────────────────────────────────────────

def implement_with_k2(spec: dict, repo: str, issue_number: str, cwd: str) -> list[dict]:
    """
    Ask K2-Think to implement the spec. Returns list of {path, content} dicts.
    """
    tree = get_repo_tree(cwd)
    existing = read_relevant_files(cwd, spec.get("files_to_modify", []))

    steps = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(spec.get("implementation_steps", [])))
    criteria = "\n".join(f"  - {c}" for c in spec.get("acceptance_criteria", []))

    system = (
        "You are an expert software engineer. You implement GitHub issues precisely and minimally. "
        "You always respond with valid JSON — no markdown fences, no extra prose."
    )

    user = f"""Implement this GitHub issue in the {repo} repository.

## Issue #{issue_number}: {spec.get("title", "")}

{spec.get("summary", "")}

## Implementation steps
{steps}

## Acceptance criteria
{criteria}

## Repository file tree (truncated)
{tree}

## Current content of relevant files
{existing}

## Instructions
Produce the COMPLETE updated content for every file that needs to change.
Return ONLY a JSON array — no markdown, no explanation:

[
  {{
    "path": "relative/path/to/file.tsx",
    "content": "full file content here"
  }}
]

Include only files you actually modified. Keep changes minimal and focused.
"""

    raw = k2_complete(system, user, max_tokens=16000)

    # Extract JSON array from response
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise RuntimeError(f"K2 returned no JSON array. Response tail: {raw[-300:]}")

    import json
    files = json.loads(match.group(0))
    log.info("K2 produced %d file(s)", len(files))
    return files


def apply_files(files: list[dict], cwd: str) -> list[str]:
    changed = []
    for f in files:
        path = f.get("path", "").lstrip("/")
        content = f.get("content", "")
        if not path or not content:
            continue
        full_path = os.path.join(cwd, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as fh:
            fh.write(content)
        changed.append(path)
        log.info("Wrote %s (%d bytes)", path, len(content))
    return changed


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "backend": "k2-think", "model": K2_MODEL}


@app.post("/implement")
def implement(req: ImplementRequest, x_factory_secret: str = Header(default="")):
    check_auth(x_factory_secret)

    spec = req.spec
    branch = re.sub(r"[^a-zA-Z0-9/_-]", "-", spec.get("branch_name", f"feature/issue-{req.issue_number}"))[:80]

    log.info("Implementing repo=%s issue=%s branch=%s", req.repo, req.issue_number, branch)

    try:
        with cloned_repo(req.repo, req.github_token, req.base_branch) as tmpdir:
            _run(["git", "checkout", "-b", branch], cwd=tmpdir)

            files = implement_with_k2(spec, req.repo, req.issue_number, tmpdir)
            changed = apply_files(files, tmpdir)

            if not changed:
                return {"success": False, "error": "K2 produced no file changes", "branch": branch}

            _run(["git", "add", "-A"], cwd=tmpdir)
            commit_msg = (
                f"feat: implement #{req.issue_number} — {spec.get('title', 'auto')}\n\n"
                f"Closes #{req.issue_number}\nGenerated by Software Factory (K2-Think)."
            )
            _run(["git", "commit", "-m", commit_msg], cwd=tmpdir)
            _run(["git", "push", "origin", branch, "--force-with-lease"], cwd=tmpdir)

            sha = _run(["git", "rev-parse", "HEAD"], cwd=tmpdir).stdout.strip()

            return {
                "success": True,
                "branch": branch,
                "commit_sha": sha,
                "files_changed": "\n".join(f"- `{f}`" for f in changed),
                "spec_summary": spec.get("summary", ""),
                "acceptance_criteria": "\n".join(f"- [ ] {c}" for c in spec.get("acceptance_criteria", [])),
            }

    except Exception as exc:
        log.exception("Implementation failed")
        return {"success": False, "error": str(exc), "branch": branch}


@app.post("/deploy")
def deploy(req: DeployRequest, x_factory_secret: str = Header(default="")):
    check_auth(x_factory_secret)

    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        return {"success": False, "error": "Render creds not set", "preview_url": None, "status": "skipped"}

    headers = {"Authorization": f"Bearer {RENDER_API_KEY}", "Content-Type": "application/json"}
    start = time.time()

    resp = httpx.post(
        f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys",
        headers=headers, json={"clearCache": False}, timeout=30,
    )
    resp.raise_for_status()
    deploy_id = (resp.json().get("deploy") or resp.json()).get("id")
    log.info("Deploy triggered: %s", deploy_id)

    status = "pending"
    preview_url = None
    for _ in range(40):
        time.sleep(15)
        try:
            poll = httpx.get(
                f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys/{deploy_id}",
                headers=headers, timeout=15,
            )
            status = poll.json().get("status", "pending")
            if status == "live":
                svc = httpx.get(f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}", headers=headers, timeout=15)
                preview_url = svc.json().get("serviceDetails", {}).get("url")
                break
            if status in ("failed", "canceled"):
                break
        except Exception as e:
            log.warning("Poll error: %s", e)

    return {
        "success": status == "live",
        "preview_url": preview_url,
        "status": status,
        "deploy_id": deploy_id,
        "build_duration_s": int(time.time() - start),
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
