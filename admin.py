import os
import json
import shutil
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from auth import get_current_user, get_user_dir, _hash_pin, _username_from_name

router = APIRouter(prefix="/api/admin")

USERS_DIR = Path(os.path.dirname(__file__)) / "users"


# ── Helpers ─────────────────────────────────────────────────────────

def _require_admin(request: Request):
    """Check the session cookie, load profile, verify is_admin.
    Returns (user_dict, None) on success or (None, JSONResponse) on failure.
    """
    user = get_current_user(request)
    if user is None:
        return None, JSONResponse({"error": "not authenticated"}, status_code=401)
    if not user.get("is_admin", False):
        return None, JSONResponse({"error": "admin access required"}, status_code=403)
    return user, None


def _user_stats(username: str) -> dict:
    """Scan a user directory and return stats."""
    user_dir = get_user_dir(username)
    history_dir = user_dir / "history"
    skills_dir = user_dir / "skills"

    conversation_count = 0
    message_count = 0
    last_active = None

    if history_dir.exists():
        for f in history_dir.iterdir():
            if f.suffix == ".json":
                try:
                    with open(f) as fh:
                        convo = json.load(fh)
                    conversation_count += 1
                    message_count += len(convo.get("messages", []))
                    updated = convo.get("updated", convo.get("created", ""))
                    if updated and (last_active is None or updated > last_active):
                        last_active = updated
                except (json.JSONDecodeError, KeyError):
                    continue

    skill_count = 0
    if skills_dir.exists():
        for entry in skills_dir.iterdir():
            if entry.is_dir() and (entry / "SKILL.md").exists():
                skill_count += 1

    return {
        "conversations": conversation_count,
        "skills": skill_count,
        "messages": message_count,
        "last_active": last_active,
    }


# ── Task 2: User management endpoints ──────────────────────────────

@router.get("/users")
async def list_users(request: Request):
    """List all users with stats."""
    admin, err = _require_admin(request)
    if err:
        return err

    users = []
    if USERS_DIR.exists():
        for entry in sorted(USERS_DIR.iterdir()):
            profile_path = entry / "profile.json"
            if entry.is_dir() and profile_path.exists():
                with open(profile_path) as f:
                    profile = json.load(f)
                stats = _user_stats(entry.name)
                users.append({
                    "username": entry.name,
                    "name": profile["name"],
                    "is_admin": profile.get("is_admin", False),
                    **stats,
                })
    return JSONResponse(users)


@router.post("/users")
async def create_user(request: Request):
    """Create a new user with name and PIN."""
    admin, err = _require_admin(request)
    if err:
        return err

    body = await request.json()
    name = body.get("name", "").strip()
    pin = body.get("pin", "").strip()

    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    if not pin or len(pin) != 4 or not pin.isdigit():
        return JSONResponse({"error": "PIN must be exactly 4 digits"}, status_code=400)

    username = _username_from_name(name)
    if not username:
        return JSONResponse({"error": "invalid name"}, status_code=400)

    user_dir = get_user_dir(username)
    if user_dir.exists():
        return JSONResponse({"error": "user already exists"}, status_code=409)

    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "skills").mkdir(exist_ok=True)
    (user_dir / "history").mkdir(exist_ok=True)

    profile = {"name": name, "pin_hash": _hash_pin(pin)}
    with open(user_dir / "profile.json", "w") as f:
        json.dump(profile, f, indent=2)

    return JSONResponse({"username": username, "name": name}, status_code=201)


@router.put("/users/{username}/pin")
async def reset_pin(username: str, request: Request):
    """Reset a user's PIN."""
    admin, err = _require_admin(request)
    if err:
        return err

    user_dir = get_user_dir(username)
    profile_path = user_dir / "profile.json"
    if not profile_path.exists():
        return JSONResponse({"error": "user not found"}, status_code=404)

    body = await request.json()
    pin = body.get("pin", "").strip()
    if not pin or len(pin) != 4 or not pin.isdigit():
        return JSONResponse({"error": "PIN must be exactly 4 digits"}, status_code=400)

    with open(profile_path) as f:
        profile = json.load(f)
    profile["pin_hash"] = _hash_pin(pin)
    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2)

    return JSONResponse({"ok": True})


@router.delete("/users/{username}")
async def delete_user(username: str, request: Request):
    """Delete a user and all their data. Cannot delete yourself."""
    admin, err = _require_admin(request)
    if err:
        return err

    if username == admin["username"]:
        return JSONResponse({"error": "cannot delete yourself"}, status_code=400)

    user_dir = get_user_dir(username)
    if not user_dir.exists():
        return JSONResponse({"error": "user not found"}, status_code=404)

    shutil.rmtree(user_dir)
    return JSONResponse({"ok": True})


# ── Task 3: System stats and model status ───────────────────────────

@router.get("/system")
async def system_stats(request: Request):
    """Return system stats: memory, CPU load, disk, uptime."""
    admin, err = _require_admin(request)
    if err:
        return err

    stats = {}

    # Memory from /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    meminfo[key] = int(parts[1])  # value in kB
            total = meminfo.get("MemTotal", 0)
            available = meminfo.get("MemAvailable", 0)
            stats["memory"] = {
                "total_mb": round(total / 1024),
                "available_mb": round(available / 1024),
                "used_mb": round((total - available) / 1024),
                "percent": round((total - available) / total * 100, 1) if total else 0,
            }
    except Exception:
        stats["memory"] = None

    # CPU load from /proc/loadavg
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            stats["cpu"] = {
                "load_1m": float(parts[0]),
                "load_5m": float(parts[1]),
                "load_15m": float(parts[2]),
            }
    except Exception:
        stats["cpu"] = None

    # Disk usage
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - free
        stats["disk"] = {
            "total_gb": round(total / (1024 ** 3), 1),
            "used_gb": round(used / (1024 ** 3), 1),
            "free_gb": round(free / (1024 ** 3), 1),
            "percent": round(used / total * 100, 1) if total else 0,
        }
    except Exception:
        stats["disk"] = None

    # Uptime from /proc/uptime
    try:
        with open("/proc/uptime") as f:
            uptime_secs = float(f.read().split()[0])
            days = int(uptime_secs // 86400)
            hours = int((uptime_secs % 86400) // 3600)
            minutes = int((uptime_secs % 3600) // 60)
            stats["uptime"] = f"{days}d {hours}h {minutes}m" 
    except Exception:
        stats["uptime"] = None

    # CPU temperature (Raspberry Pi)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp_c = int(f.read().strip()) / 1000.0
            stats["temperature"] = round(temp_c, 1)
    except Exception:
        stats["temperature"] = None

    return JSONResponse(stats)


@router.get("/models")
async def model_status(request: Request):
    """Return cached models and cache age."""
    admin, err = _require_admin(request)
    if err:
        return err

    from main import get_model_cache_info
    import asyncio
    info = get_model_cache_info()
    now = asyncio.get_event_loop().time()
    cache_age = now - info["last_fetch"] if info["last_fetch"] else None
    return JSONResponse({
        "models": info["models"],
        "count": info["count"],
        "cache_age_seconds": round(cache_age) if cache_age is not None else None,
    })


@router.post("/models/refresh")
async def refresh_models(request: Request):
    """Clear model cache and refetch."""
    admin, err = _require_admin(request)
    if err:
        return err

    from main import clear_model_cache, fetch_free_models
    clear_model_cache()
    models = await fetch_free_models()
    return JSONResponse({"ok": True, "count": len(models)})


# ── Task 4: Usage stats ────────────────────────────────────────────

@router.get("/stats")
async def usage_stats(request: Request):
    """Scan all user directories and compute aggregate usage stats."""
    admin, err = _require_admin(request)
    if err:
        return err

    total_users = 0
    total_conversations = 0
    total_messages = 0
    per_user = []
    skill_counts = {}  # skill_name -> conversation count
    model_counts = {}  # model_id -> conversation count

    if USERS_DIR.exists():
        for entry in sorted(USERS_DIR.iterdir()):
            profile_path = entry / "profile.json"
            if not entry.is_dir() or not profile_path.exists():
                continue

            total_users += 1
            with open(profile_path) as f:
                profile = json.load(f)

            user_convos = 0
            user_messages = 0
            history_dir = entry / "history"

            if history_dir.exists():
                for f in history_dir.iterdir():
                    if f.suffix == ".json":
                        try:
                            with open(f) as fh:
                                convo = json.load(fh)
                            user_convos += 1
                            msg_count = len(convo.get("messages", []))
                            user_messages += msg_count

                            skill = convo.get("skill")
                            if skill:
                                skill_counts[skill] = skill_counts.get(skill, 0) + 1

                            model = convo.get("model", "")
                            if model:
                                model_counts[model] = model_counts.get(model, 0) + 1
                        except (json.JSONDecodeError, KeyError):
                            continue

            total_conversations += user_convos
            total_messages += user_messages

            per_user.append({
                "username": entry.name,
                "name": profile["name"],
                "conversations": user_convos,
                "messages": user_messages,
            })

    # Sort skills and models by count descending
    top_skills = sorted(skill_counts.items(), key=lambda x: -x[1])
    top_models = sorted(model_counts.items(), key=lambda x: -x[1])

    return JSONResponse({
        "total_users": total_users,
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "per_user": per_user,
        "top_skills": [{"name": s, "conversations": c} for s, c in top_skills],
        "top_models": [{"id": m, "name": m, "conversations": c} for m, c in top_models],
    })
