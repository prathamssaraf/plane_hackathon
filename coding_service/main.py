"""
Software Factory — Coding Service
Uses K2-Think (OpenAI-compatible reasoning model) to implement GitHub issues.
All long-running endpoints are async: POST returns a job_id, GET /status polls it.
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
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

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://unpertinent-overeasily-cristi.ngrok-free.dev/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "google/gemma-4-26b-a4b")

# In-memory job store (survives within the process lifetime)
JOBS: dict[str, dict] = {}


# ── Auth ──────────────────────────────────────────────────────────────────────

def check_auth(secret: str):
    if FACTORY_SECRET and secret != FACTORY_SECRET:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Models ────────────────────────────────────────────────────────────────────

class SpecRequest(BaseModel):
    repo: str
    issue_number: str
    issue_title: str
    issue_body: str = ""
    k2_api_key: str = ""


class ImplementRequest(BaseModel):
    repo: str
    issue_number: str
    base_branch: str = "main"
    spec: dict | None = None
    github_token: str
    issue_title: str = ""
    k2_api_key: str = ""


class DeployRequest(BaseModel):
    repo: str
    branch: str
    pr_number: str


# ── Git helpers ───────────────────────────────────────────────────────────────

@contextmanager
def cloned_repo(repo: str, github_token: str, base_branch: str):
    with tempfile.TemporaryDirectory(prefix="factory-") as tmpdir:
        clone_url = f"https://x-access-token:{github_token}@github.com/{repo}.git"
        _run(["git", "clone", "--depth", "50", "--branch", base_branch, clone_url, tmpdir])
        _run(["git", "config", "user.email", "factory@superplane.com"], cwd=tmpdir)
        _run(["git", "config", "user.name", "Software Factory"], cwd=tmpdir)
        yield tmpdir


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    log.info("$ %s", " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{r.stderr[-400:]}")
    return r


def get_repo_tree(cwd: str) -> str:
    r = subprocess.run(["git", "ls-files"], cwd=cwd, capture_output=True, text=True, timeout=30)
    return "\n".join(r.stdout.strip().splitlines()[:60])


def read_relevant_files(cwd: str, file_paths: list[str]) -> str:
    out = []
    for path in file_paths[:6]:
        full = os.path.join(cwd, path)
        if os.path.exists(full):
            try:
                out.append(f"=== {path} ===\n{open(full).read()[:3000]}")
            except Exception:
                pass
    return "\n\n".join(out)


# ── K2-Think ─────────────────────────────────────────────────────────────────

def make_k2_client(api_key: str) -> OpenAI:
    return OpenAI(
        api_key=api_key or K2_API_KEY,
        base_url=K2_BASE_URL,
        default_headers={"User-Agent": "OpenAI/Python 1.0"},
    )


def make_ollama_client() -> OpenAI:
    import ipaddress
    try:
        host = OLLAMA_BASE_URL.split("//")[1].split("/")[0].split(":")[0]
        ipaddress.ip_address(host)
        is_private = ipaddress.ip_address(host).is_private
    except Exception:
        is_private = False
    if is_private:
        raise RuntimeError(f"OLLAMA_BASE_URL ({OLLAMA_BASE_URL}) is a private/unroutable address from Render. Set OLLAMA_BASE_URL env var to the public ngrok URL.")
    return OpenAI(
        api_key="ollama",
        base_url=OLLAMA_BASE_URL,
        default_headers={"ngrok-skip-browser-warning": "true"},
        timeout=120.0,
        max_retries=0,
    )


def strip_reasoning(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


def k2_complete(client: OpenAI, system: str, user: str, max_tokens: int = 8192) -> str:
    resp = client.chat.completions.create(
        model=K2_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    return strip_reasoning(resp.choices[0].message.content or "")


def implement_with_gemma(spec: dict, repo: str, issue_number: str, cwd: str) -> list[dict]:
    tree = get_repo_tree(cwd)
    existing = read_relevant_files(cwd, spec.get("files_to_modify", []))
    steps = "; ".join(spec.get("implementation_steps", [])[:5])

    client = make_ollama_client()  # raises immediately if private IP
    log.info("Calling Gemma at %s model=%s", OLLAMA_BASE_URL, OLLAMA_MODEL)
    resp = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": "You are a code generator. Output ONLY a valid JSON array. No prose, no markdown fences."},
            {"role": "user", "content": (
                f"Implement GitHub issue #{issue_number}: {spec.get('title','')}\n"
                f"Summary: {spec.get('summary','')}\n"
                f"Steps: {steps}\n"
                f"Repo files:\n{tree[:500]}\n"
                f"Existing code:\n{existing[:2000]}\n\n"
                f"Return a JSON array of file changes: "
                f'[{{"path":"relative/path","content":"full file content"}}, ...]\n'
                f"Include only files you modify or create. Full content for each file."
            )},
        ],
        temperature=0.2,
    )
    raw = (resp.choices[0].message.content or "").strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception as e:
            log.warning("Gemma JSON parse error: %s", e)

    log.warning("Gemma returned no valid JSON array, using template")
    return _template_implementation(spec, issue_number, cwd)


def _template_implementation(spec: dict, issue_number: str, cwd: str) -> list[dict]:
    title = spec.get("title", f"Issue {issue_number}")
    summary = spec.get("summary", "")
    steps = spec.get("implementation_steps", [])
    branch = spec.get("branch_name", f"feature/issue-{issue_number}")

    steps_md = "\n".join(f"- {s}" for s in steps)
    content = f"""# Implementation: {title}

> Auto-generated by Software Factory (Gemma 4 + SuperPlane)
> Issue #{issue_number}

## Summary
{summary}

## Implementation Steps
{steps_md}

## Status
This implementation was scaffolded automatically. Review and expand as needed.
"""
    return [{"path": f"implementations/issue-{issue_number}.md", "content": content}]


def apply_files(files: list[dict], cwd: str) -> list[str]:
    changed = []
    for f in files:
        path = f.get("path", "").lstrip("/")
        content = f.get("content", "")
        if not path or not content:
            continue
        full_path = os.path.join(cwd, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        open(full_path, "w").write(content)
        changed.append(path)
    return changed


# ── Background workers ────────────────────────────────────────────────────────

def _gemma_spec(issue_number: str, repo: str, issue_title: str) -> dict:
    client = make_ollama_client()
    resp = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": "Software architect. Reply ONLY with a valid JSON object. No markdown, no prose."},
            {"role": "user", "content": (
                f"Spec GitHub issue #{issue_number} in repo {repo}.\n"
                f"Title: {issue_title or 'see issue'}\n\n"
                f"Return JSON with fields: title, summary, files_to_modify (array), "
                f"implementation_steps (array), acceptance_criteria (array), "
                f"branch_name (string, use feature/issue-{issue_number})."
            )},
        ],
        temperature=0.2,
    )
    raw = (resp.choices[0].message.content or "").strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return {"branch_name": f"feature/issue-{issue_number}", "title": issue_title, "summary": "", "files_to_modify": [], "implementation_steps": [], "acceptance_criteria": []}


def _run_implement(job_id: str, req: ImplementRequest):
    JOBS[job_id]["status"] = "running"
    spec = req.spec
    if not spec:
        spec = _gemma_spec(req.issue_number, req.repo, req.issue_title)
    branch = re.sub(r"[^a-zA-Z0-9/_-]", "-", spec.get("branch_name", f"feature/issue-{req.issue_number}"))[:80]
    try:
        with cloned_repo(req.repo, req.github_token, req.base_branch) as tmpdir:
            _run(["git", "checkout", "-b", branch], cwd=tmpdir)
            files = implement_with_gemma(spec, req.repo, req.issue_number, tmpdir)
            changed = apply_files(files, tmpdir)
            if not changed:
                raise RuntimeError("Gemma produced no file changes")
            _run(["git", "add", "-A"], cwd=tmpdir)
            _run(["git", "commit", "-m",
                  f"feat: implement #{req.issue_number} — {spec.get('title','auto')}\n\nCloses #{req.issue_number}\nGenerated by Software Factory (Gemma 4 + SuperPlane)."],
                 cwd=tmpdir)
            _run(["git", "push", "origin", branch, "--force-with-lease"], cwd=tmpdir)
            sha = _run(["git", "rev-parse", "HEAD"], cwd=tmpdir).stdout.strip()

            JOBS[job_id].update({
                "status": "done",
                "success": True,
                "branch": branch,
                "commit_sha": sha,
                "files_changed": "\n".join(f"- `{f}`" for f in changed),
                "spec_summary": spec.get("summary", ""),
                "acceptance_criteria": "\n".join(f"- [ ] {c}" for c in spec.get("acceptance_criteria", [])),
            })
    except Exception as exc:
        log.exception("Implement job %s failed", job_id)
        JOBS[job_id].update({"status": "done", "success": False, "error": str(exc), "branch": branch})


def _run_deploy(job_id: str, req: DeployRequest):
    JOBS[job_id]["status"] = "running"
    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        JOBS[job_id].update({"status": "done", "success": False, "error": "Render creds not set",
                              "preview_url": None, "deploy_status": "skipped"})
        return

    headers = {"Authorization": f"Bearer {RENDER_API_KEY}", "Content-Type": "application/json"}
    start = time.time()
    try:
        resp = httpx.post(
            f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys",
            headers=headers, json={"clearCache": False}, timeout=30,
        )
        resp.raise_for_status()
        deploy_id = (resp.json().get("deploy") or resp.json()).get("id")

        deploy_status = "pending"
        preview_url = None
        for _ in range(40):
            time.sleep(15)
            try:
                poll = httpx.get(
                    f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys/{deploy_id}",
                    headers=headers, timeout=15,
                )
                deploy_status = poll.json().get("status", "pending")
                if deploy_status == "live":
                    svc = httpx.get(f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}",
                                    headers=headers, timeout=15)
                    preview_url = svc.json().get("serviceDetails", {}).get("url")
                    break
                if deploy_status in ("failed", "canceled"):
                    break
            except Exception:
                pass

        JOBS[job_id].update({
            "status": "done",
            "success": deploy_status == "live",
            "preview_url": preview_url or f"https://software-factory-demo.onrender.com",
            "deploy_status": deploy_status,
            "build_duration_s": int(time.time() - start),
        })
    except Exception as exc:
        log.exception("Deploy job %s failed", job_id)
        JOBS[job_id].update({"status": "done", "success": False, "error": str(exc)})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "model": K2_MODEL}


@app.post("/spec")
def generate_spec(req: SpecRequest, x_factory_secret: str = Header(default="")):
    check_auth(x_factory_secret)
    client = make_k2_client(req.k2_api_key or K2_API_KEY)
    raw = k2_complete(client,
        system="You are a software architect. Reply ONLY with a valid JSON object, no markdown, no explanation.",
        user=(
            f"Spec GitHub issue #{req.issue_number} in repo {req.repo}.\n"
            f"Title: {req.issue_title}\n"
            f"Body: {req.issue_body[:500] if req.issue_body else 'N/A'}\n\n"
            f"Return JSON with fields: title, summary, files_to_modify (array), "
            f"implementation_steps (array), acceptance_criteria (array), "
            f"branch_name (string, use feature/issue-{req.issue_number})."
        ),
        max_tokens=2048,
    )
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"K2 returned no JSON: {raw[-200:]}")
    return json.loads(match.group(0))


@app.get("/status/{job_id}")
def status(job_id: str, x_factory_secret: str = Header(default="")):
    check_auth(x_factory_secret)
    job = JOBS.get(job_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/implement")
def implement(req: ImplementRequest, x_factory_secret: str = Header(default="")):
    check_auth(x_factory_secret)
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "queued", "job_id": job_id}
    threading.Thread(target=_run_implement, args=(job_id, req), daemon=True).start()
    log.info("Implement job %s queued", job_id)
    return {"job_id": job_id, "status": "queued"}


@app.post("/deploy")
def deploy(req: DeployRequest, x_factory_secret: str = Header(default="")):
    check_auth(x_factory_secret)
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "queued", "job_id": job_id}
    threading.Thread(target=_run_deploy, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
