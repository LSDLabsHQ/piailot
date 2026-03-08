import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from auth import get_current_user, get_user_dir

router = APIRouter(prefix="/api/conversations")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_dir(username: str) -> Path:
    return get_user_dir(username) / "history"


def _convo_path(username: str, convo_id: str) -> Path:
    return _history_dir(username) / f"{convo_id}.json"


def _require_user(request: Request):
    user = get_current_user(request)
    if user is None:
        return None, JSONResponse({"error": "not authenticated"}, status_code=401)
    return user, None


@router.get("")
async def list_conversations(request: Request):
    user, err = _require_user(request)
    if err:
        return err

    history = _history_dir(user["username"])
    if not history.exists():
        return JSONResponse([])

    convos = []
    for f in history.iterdir():
        if f.suffix == ".json":
            try:
                with open(f) as fh:
                    data = json.load(fh)
                convos.append({
                    "id": data["id"],
                    "title": data.get("title", ""),
                    "skill": data.get("skill"),
                    "model": data.get("model", ""),
                    "updated": data.get("updated", data.get("created", "")),
                })
            except (json.JSONDecodeError, KeyError):
                continue

    convos.sort(key=lambda c: c["updated"], reverse=True)
    return JSONResponse(convos)


@router.post("")
async def create_conversation(request: Request):
    user, err = _require_user(request)
    if err:
        return err

    body = await request.json() if (await request.body()) else {}
    convo_id = uuid.uuid4().hex[:12]
    now = _now_iso()

    convo = {
        "id": convo_id,
        "title": "New conversation",
        "skill": body.get("skill"),
        "model": body.get("model", ""),
        "messages": [],
        "created": now,
        "updated": now,
    }

    history = _history_dir(user["username"])
    history.mkdir(parents=True, exist_ok=True)
    with open(_convo_path(user["username"], convo_id), "w") as f:
        json.dump(convo, f, indent=2)

    return JSONResponse(convo, status_code=201)


@router.get("/{convo_id}")
async def get_conversation(convo_id: str, request: Request):
    user, err = _require_user(request)
    if err:
        return err

    path = _convo_path(user["username"], convo_id)
    if not path.exists():
        return JSONResponse({"error": "conversation not found"}, status_code=404)

    with open(path) as f:
        convo = json.load(f)

    return JSONResponse(convo)


@router.put("/{convo_id}")
async def update_conversation(convo_id: str, request: Request):
    user, err = _require_user(request)
    if err:
        return err

    path = _convo_path(user["username"], convo_id)
    if not path.exists():
        return JSONResponse({"error": "conversation not found"}, status_code=404)

    with open(path) as f:
        convo = json.load(f)

    body = await request.json()

    if "messages" in body:
        convo["messages"] = body["messages"]
        # Auto-generate title from first user message
        for msg in body["messages"]:
            if msg.get("role") == "user" and msg.get("content"):
                convo["title"] = msg["content"][:50]
                break

    if "skill" in body:
        convo["skill"] = body["skill"]
    if "model" in body:
        convo["model"] = body["model"]

    convo["updated"] = _now_iso()

    with open(path, "w") as f:
        json.dump(convo, f, indent=2)

    return JSONResponse(convo)


@router.delete("/{convo_id}")
async def delete_conversation(convo_id: str, request: Request):
    user, err = _require_user(request)
    if err:
        return err

    path = _convo_path(user["username"], convo_id)
    if not path.exists():
        return JSONResponse({"error": "conversation not found"}, status_code=404)

    path.unlink()
    return JSONResponse({"ok": True})
