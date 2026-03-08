import os
import re
import json
import hashlib
from pathlib import Path
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

router = APIRouter(prefix="/api/auth")

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET environment variable is required. See .env.example")
COOKIE_NAME = "piailot_session"
MAX_AGE = 30 * 24 * 60 * 60  # 30 days in seconds
BASE_DIR = Path(os.path.dirname(__file__))
USERS_DIR = BASE_DIR / "users"

serializer = URLSafeTimedSerializer(SESSION_SECRET)


def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()


def _username_from_name(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def get_user_dir(username: str) -> Path:
    return USERS_DIR / username


def get_current_user(request: Request) -> dict | None:
    """Return the current user dict from the session cookie, or None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        username = serializer.loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None

    profile_path = get_user_dir(username) / "profile.json"
    if not profile_path.exists():
        return None

    with open(profile_path) as f:
        profile = json.load(f)

    return {"username": username, "name": profile["name"], "is_admin": profile.get("is_admin", False)}


def _set_session_cookie(response: Response, username: str) -> None:
    token = serializer.dumps(username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
    )


class RegisterRequest(BaseModel):
    name: str
    pin: str


class LoginRequest(BaseModel):
    username: str
    pin: str


@router.get("/me")
async def me(request: Request):
    user = get_current_user(request)
    if user is None:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    return JSONResponse(user)


@router.get("/users")
async def list_users():
    users = []
    if USERS_DIR.exists():
        for entry in sorted(USERS_DIR.iterdir()):
            profile_path = entry / "profile.json"
            if entry.is_dir() and profile_path.exists():
                with open(profile_path) as f:
                    profile = json.load(f)
                users.append({"username": entry.name, "name": profile["name"]})
    return JSONResponse(users)


@router.post("/register")
async def register(body: RegisterRequest):
    name = body.name.strip()
    pin = body.pin.strip()

    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    if not re.match(r"^\d{4}$", pin):
        return JSONResponse({"error": "PIN must be exactly 4 digits"}, status_code=400)

    username = _username_from_name(name)
    if not username:
        return JSONResponse({"error": "invalid name"}, status_code=400)

    user_dir = get_user_dir(username)
    if user_dir.exists():
        return JSONResponse({"error": "user already exists"}, status_code=409)

    # Create user directory structure
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "skills").mkdir(exist_ok=True)
    (user_dir / "history").mkdir(exist_ok=True)

    profile = {"name": name, "pin_hash": _hash_pin(pin)}
    with open(user_dir / "profile.json", "w") as f:
        json.dump(profile, f, indent=2)

    response = JSONResponse({"username": username, "name": name})
    _set_session_cookie(response, username)
    return response


@router.post("/login")
async def login(body: LoginRequest):
    username = body.username.strip().lower()
    pin = body.pin.strip()

    profile_path = get_user_dir(username) / "profile.json"
    if not profile_path.exists():
        return JSONResponse({"error": "user not found"}, status_code=401)

    with open(profile_path) as f:
        profile = json.load(f)

    if profile["pin_hash"] != _hash_pin(pin):
        return JSONResponse({"error": "invalid PIN"}, status_code=401)

    response = JSONResponse({"username": username, "name": profile["name"]})
    _set_session_cookie(response, username)
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(key=COOKIE_NAME)
    return response
