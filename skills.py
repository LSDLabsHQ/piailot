import re
import shutil
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from auth import get_current_user, get_user_dir

router = APIRouter(prefix="/api/skills")

AVAILABLE_TOOLS = ["web_search", "web_fetch", "calculator", "datetime"]
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_NAME_LEN = 64


class SkillCreate(BaseModel):
    name: str
    description: str
    tools: list[str]
    system_prompt: str


class SkillUpdate(BaseModel):
    description: str | None = None
    tools: list[str] | None = None
    system_prompt: str | None = None


def _validate_name(name: str) -> str | None:
    """Return error message if name is invalid, else None."""
    if not name or len(name) > MAX_NAME_LEN:
        return f"name must be 1-{MAX_NAME_LEN} characters"
    if not NAME_PATTERN.match(name):
        return "name must be lowercase alphanumeric and hyphens, starting with alphanumeric"
    return None


def _validate_tools(tools: list[str]) -> str | None:
    """Return error message if any tool is invalid, else None."""
    bad = [t for t in tools if t not in AVAILABLE_TOOLS]
    if bad:
        return f"invalid tools: {bad}. available: {AVAILABLE_TOOLS}"
    return None


def _skill_dir(username: str, name: str) -> Path:
    return get_user_dir(username) / "skills" / name


def _skill_path(username: str, name: str) -> Path:
    return _skill_dir(username, name) / "SKILL.md"


def _build_skill_md(name: str, description: str, tools: list[str], system_prompt: str) -> str:
    tools_str = ", ".join(tools)
    return f"""---
name: {name}
description: {description}
tools: [{tools_str}]
---

{system_prompt}
"""


def _parse_skill_md(content: str) -> dict | None:
    """Parse SKILL.md frontmatter and body. Returns dict or None on failure."""
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    frontmatter = parts[1].strip()
    body = parts[2].strip()

    meta = {}
    for line in frontmatter.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()

    name = meta.get("name", "")
    description = meta.get("description", "")
    tools_raw = meta.get("tools", "[]")
    # Parse [tool1, tool2] format
    tools_raw = tools_raw.strip("[] ")
    if tools_raw:
        tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
    else:
        tools = []

    return {
        "name": name,
        "description": description,
        "tools": tools,
        "system_prompt": body,
    }


def _require_user(request: Request):
    user = get_current_user(request)
    if user is None:
        return None, JSONResponse({"error": "not authenticated"}, status_code=401)
    return user, None


@router.get("")
async def list_skills(request: Request):
    user, err = _require_user(request)
    if err:
        return err

    username = user["username"]
    skills_dir = get_user_dir(username) / "skills"
    if not skills_dir.exists():
        return JSONResponse([])

    result = []
    for entry in sorted(skills_dir.iterdir()):
        md_path = entry / "SKILL.md"
        if entry.is_dir() and md_path.exists():
            parsed = _parse_skill_md(md_path.read_text())
            if parsed:
                result.append({
                    "name": parsed["name"],
                    "description": parsed["description"],
                    "tools": parsed["tools"],
                })
    return JSONResponse(result)


@router.get("/{name}")
async def get_skill(name: str, request: Request):
    user, err = _require_user(request)
    if err:
        return err

    username = user["username"]
    md_path = _skill_path(username, name)
    if not md_path.exists():
        return JSONResponse({"error": "skill not found"}, status_code=404)

    parsed = _parse_skill_md(md_path.read_text())
    if not parsed:
        return JSONResponse({"error": "skill file corrupt"}, status_code=500)

    return JSONResponse(parsed)


@router.post("")
async def create_skill(body: SkillCreate, request: Request):
    user, err = _require_user(request)
    if err:
        return err

    username = user["username"]

    name_err = _validate_name(body.name)
    if name_err:
        return JSONResponse({"error": name_err}, status_code=400)

    tools_err = _validate_tools(body.tools)
    if tools_err:
        return JSONResponse({"error": tools_err}, status_code=400)

    skill_d = _skill_dir(username, body.name)
    if skill_d.exists():
        return JSONResponse({"error": "skill already exists"}, status_code=409)

    skill_d.mkdir(parents=True, exist_ok=True)
    md = _build_skill_md(body.name, body.description, body.tools, body.system_prompt)
    _skill_path(username, body.name).write_text(md)

    return JSONResponse({"ok": True, "name": body.name}, status_code=201)


@router.put("/{name}")
async def update_skill(name: str, body: SkillUpdate, request: Request):
    user, err = _require_user(request)
    if err:
        return err

    username = user["username"]
    md_path = _skill_path(username, name)

    if not md_path.exists():
        return JSONResponse({"error": "skill not found"}, status_code=404)

    existing = _parse_skill_md(md_path.read_text())
    if not existing:
        return JSONResponse({"error": "skill file corrupt"}, status_code=500)

    description = body.description if body.description is not None else existing["description"]
    tools = body.tools if body.tools is not None else existing["tools"]
    system_prompt = body.system_prompt if body.system_prompt is not None else existing["system_prompt"]

    if body.tools is not None:
        tools_err = _validate_tools(tools)
        if tools_err:
            return JSONResponse({"error": tools_err}, status_code=400)

    md = _build_skill_md(name, description, tools, system_prompt)
    md_path.write_text(md)

    return JSONResponse({"ok": True, "name": name})


@router.delete("/{name}")
async def delete_skill(name: str, request: Request):
    user, err = _require_user(request)
    if err:
        return err

    username = user["username"]
    skill_d = _skill_dir(username, name)

    if not skill_d.exists():
        return JSONResponse({"error": "skill not found"}, status_code=404)

    shutil.rmtree(skill_d)
    return JSONResponse({"ok": True})

# Public alias for use by other modules
parse_skill_md = _parse_skill_md
