# Piailot Hidden Toolkit — Design Spec

Inspired by Claude.ai's 28 undocumented internal tools (reverse-engineered by N1-AI/claude-hidden-toolkit), adapted as piailot-native equivalents.

## Approach

Phased implementation. Four self-contained phases, each shippable independently. Tools are split into always-on (available in every conversation) and opt-in (enabled per skill).

## Architecture

### Backend: tools/ package

Split the monolithic `tools.py` into a package:

```
tools/
  __init__.py          # TOOL_DEFINITIONS, ALWAYS_ON_TOOLS, execute_tool()
  memory.py            # memory_edit, conversation_search, recent_chats
  context.py           # user_time, calculator
  search.py            # web_search, web_fetch, image_search
  data.py              # weather, places_search, sports_data
  widgets.py           # ask_user_input, message_compose, chart_display
  discovery.py         # tool_search meta-tool
```

The existing `from tools import TOOL_DEFINITIONS, execute_tool` import in `main.py` continues to work unchanged — `tools/__init__.py` re-exports everything. The `web_search` and `web_fetch` implementations are migrated as-is (same DuckDuckGo scraping, same parameters).

### execute_tool context parameter

The current `execute_tool(name, arguments)` signature gains a `context` dict:

```python
async def execute_tool(name: str, arguments: dict, context: dict = None) -> str:
```

`main.py` passes context when calling:

```python
tool_result = await execute_tool(fn_name, fn_args, context={"username": user["username"], "timezone": browser_tz})
```

User-scoped tools (memory, conversation_search, recent_chats) use `context["username"]` to locate the right `users/{username}/` directory. Context-aware tools (user_time) use `context["timezone"]`. Tools that don't need context ignore it — backwards compatible.

### Always-on vs opt-in

- **Always-on:** `memory_edit`, `conversation_search`, `recent_chats`, `user_time`, `tool_search`. Injected into every request by `main.py` regardless of skill config.
- **Opt-in:** `web_search`, `web_fetch`, `image_search`, `calculator`, `weather`, `places_search`, `sports_data`, `ask_user_input`, `message_compose`, `chart_display`. Enabled per skill in SKILL.md frontmatter.

### Always-on tool injection in main.py

Currently `main.py` has two paths: tool-use (non-streaming) when a skill enables tools, and streaming when no tools are present. With always-on tools, the tool-use path is always active since at minimum the always-on tools are available in every request.

The streaming path remains as a fallback for edge cases (e.g., if the model returns no tool calls on its first response, stream that response directly). But the initial request always includes tool definitions.

This means every conversation gains the overhead of non-streaming tool-call handling. This is acceptable because:
- Most free models on OpenRouter have limited or inconsistent streaming support anyway
- The tool loop already handles the case where no tool calls are made (emits content directly)
- Always-on tools are lightweight (memory view, datetime) and rarely add more than 1 extra round-trip

### Rich tool responses — widget delivery

Tools that produce UI widgets return structured JSON with a marker:

```json
{"__piailot_widget__": "chart", "data": {...}}
```

**Delivery mechanism:** Widget JSON is emitted as a separate SSE event before the assistant's text response:

```
data: {"__piailot_widget__": "weather", "data": {...}}\n\n
data: {"choices": [{"delta": {"content": "Here's the weather..."}, ...}]}\n\n
```

The frontend checks each SSE event for `__piailot_widget__` and dispatches to the appropriate renderer. The AI also receives the JSON as a tool result string, so it can summarize the data in its text response. Plain text tools work unchanged.

### ask_user_input round-trip

`ask_user_input` is unique: it requires user interaction mid-conversation. The round-trip:

1. Tool returns widget JSON → SSE emits widget event → assistant text streams normally
2. Frontend renders the choice widget below the assistant message
3. The tool loop completes normally (the AI summarizes the options in text)
4. User interacts with the widget (clicks, drags, etc.)
5. Frontend auto-sends a new user message with the selection: `"[User selected: Option A, Option C]"` for multi_select, `"[User ranked: 1. Option B, 2. Option A, 3. Option C]"` for rank_priorities
6. This triggers a new `/api/chat` call — a fresh request, not a continuation of the tool loop

This means `ask_user_input` does NOT pause the tool loop. It completes like any other tool, and the user's response comes back as a new conversation turn.

### Frontend libraries (CDN, lazy-loaded)

- **Chart.js** (~60KB gz) — For chart_display. Loaded on first chart encounter.
- **Leaflet** (~40KB gz) — For places_search maps. Loaded on first map encounter.
- **Everything else** — Vanilla JS/CSS.
- **Fallback** — If CDN fails (detected via `onerror` handler on the script tag + 10s load timeout), charts render as data tables, maps render as coordinate text with links to OpenStreetMap.

### Static file serving

All frontend files live in `static/` and are served by nginx (per `config/piailot-nginx.conf`). FastAPI does not mount static files. New widget CSS and helper JS go in `static/` alongside existing files.

---

## Phase 1: Always-On Tools (Memory & Context)

### memory_edit

Persistent facts about the user.

- **Storage:** `users/{username}/memory.json` — array of strings
- **Commands:** `view`, `add`, `remove`, `replace`
- **Limits:** 50 facts, 300 chars each
- **Injection:** `main.py` reads memory file on every chat request, prepends as `[User Memory]` block in system prompt. **Token budget:** The memory block is capped at 2,000 characters (~500 tokens). If total memory exceeds this, the oldest facts are truncated with a note: `"[... N more facts stored]"`. This keeps memory injection safe for models with small context windows (4K-8K).
- **Always-on**

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | Yes | `"view"`, `"add"`, `"remove"`, `"replace"` |
| `content` | string | For add | Fact text (max 300 chars) |
| `index` | integer | For remove/replace | 0-indexed position |
| `replacement` | string | For replace | New text |

### conversation_search

Keyword search across stored conversation history.

- **Storage:** Reads from existing `users/{username}/history/*.json`
- **Implementation:** String matching across message content in conversation files. Scans at most 100 most recent files (sorted by modification time) to keep performance acceptable on Raspberry Pi with SD card I/O. Times out after 5 seconds.
- **Always-on**

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search keywords |
| `max_results` | integer | No | 1-10, default 5 |

**Response:** Array of `{conversation_id, title, timestamp, matching_snippets[]}`.

### recent_chats

Time-based retrieval of recent conversations.

- **Storage:** Reads from existing history directory
- **Always-on**

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `count` | integer | No | 1-20, default 5 |
| `sort` | string | No | `"newest"` (default) or `"oldest"` |
| `before` | string | No | ISO 8601 datetime filter |
| `after` | string | No | ISO 8601 datetime filter |

**Response:** Array of `{conversation_id, title, created, updated, message_count, skill}`.

### user_time (replaces datetime)

Enhanced datetime with timezone awareness.

- **Frontend change:** Chat requests include `Intl.DateTimeFormat().resolvedOptions().timeZone` from browser. Passed via `execute_tool` context.
- **Parameters:** `timezone` (optional string). **Precedence:** explicit parameter > browser-provided context > UTC fallback. This lets the AI ask "what time is it in Tokyo?" by passing `timezone: "Asia/Tokyo"` while defaulting to the user's browser timezone for general queries.
- **Always-on**
- **Backwards compat:** Old `datetime` tool name silently maps to `user_time`.

**Response:**

```json
{
  "current_time": "2026-03-12T14:30:45+00:00",
  "timezone": "Europe/London",
  "day": "Thursday"
}
```

---

## Phase 2: Data Tools (Opt-in)

### image_search

Web image search with inline results.

- **Implementation:** DuckDuckGo image search scraping
- **No API key required**

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query |
| `max_results` | integer | No | 3-5, default 3 |

**Response:** Widget — horizontal image strip. Array of `{title, url, thumbnail_url, source}`.

**Frontend:** CSS grid of thumbnails. Click opens full-size in new tab. Vanilla JS.

### weather

Weather display with forecast.

- **Implementation:** Open-Meteo API (free, no key). Geocodes location names via their geocoding endpoint, fetches current + 5-day forecast.
- **No API key required**

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `location` | string | Yes | City name or "lat,lng" coordinates |

**Response:** Widget — weather card. `{location_name, current: {temp_c, temp_f, conditions, humidity, wind_speed}, forecast: [{date, high_c, low_c, conditions, precipitation_chance}]}`.

**Frontend:** Styled card with emoji weather icons, current conditions, forecast row. Themed to match terminal/light/soft. Vanilla JS.

### places_search

Location-based place search with optional map.

- **Implementation:** Nominatim/Overpass (free, no key) as default. Google Places as optional upgrade via `PLACES_API_KEY` env var. **Rate limiting:** Nominatim enforces 1 request/second — the implementation must include a simple rate limiter (timestamp-based, no external dependency) to avoid getting blocked.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query |
| `latitude` | number | No | Proximity bias |
| `longitude` | number | No | Proximity bias |
| `max_results` | integer | No | 1-10, default 5 |

**Response:** Widget — place list + map. Array of `{name, address, latitude, longitude, type, rating}`.

**Frontend:** Results list with Leaflet map (CDN, lazy-loaded). Markers with popups.

### sports_data

Live scores, standings, stats.

- **Implementation:** TheSportsDB (free, no key for basic) as default. Optional `SPORTS_API_KEY` for premium sources.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `type` | string | Yes | `"scores"`, `"standings"`, `"stats"` |
| `league` | string | Yes | League identifier |
| `team` | string | No | Team name filter |

**Response:** Structured JSON. Rendered as formatted table.

**Frontend:** Styled table. Vanilla JS.

---

## Phase 3: Interactive Widgets (Opt-in)

### ask_user_input

Interactive choice widgets.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `questions` | array | Yes | 1-3 question objects |

Each question: `{question: string, type: "single_select"|"multi_select"|"rank_priorities", options: string[2-6]}`.

**Frontend:**
- `single_select` — Radio buttons
- `multi_select` — Checkbox chips with selection counter
- `rank_priorities` — HTML5 native drag-and-drop reorder list
- Keyboard: arrows to navigate, Enter to select, Escape to skip
- User selections sent as a new user message automatically
- Vanilla JS/CSS

### message_compose

Message drafting with strategic variant tabs.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `kind` | string | Yes | `"email"`, `"text"`, `"other"` |
| `summary_title` | string | Yes | Card title |
| `variants` | array | Yes | Each: `{label, body, subject?}` |

**Frontend:**
- Tabbed card with variant selector
- Email: "Copy" + `mailto:` link (opens default mail client)
- Text/other: "Copy to clipboard" button
- Vanilla JS/CSS

### chart_display

Inline interactive charts.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `series` | array | Yes | Each: `{name: string, data: number[]}` |
| `style` | string | Yes | `"line"`, `"bar"`, `"scatter"` |
| `title` | string | No | Chart title |
| `x_labels` | array | No | X-axis labels |
| `y_label` | string | No | Y-axis label |

**Frontend:** Chart.js (CDN, lazy-loaded). Canvas-based, responsive, tooltips, legend toggling. Falls back to data table if CDN unavailable.

---

## Phase 4: Polish & Integration

### Skills system update

- `ALWAYS_ON_TOOLS` never appear in skill editor (implicit)
- `AVAILABLE_TOOLS` updated with all new opt-in tools
- Old `datetime` silently maps to `user_time`
- Existing skills continue to work unchanged
- **skills.html update:** The hardcoded `TOOLS` array in `static/skills.html` must be updated with the new opt-in tools. Better: replace it with a fetch from a new `GET /api/tools` endpoint that returns `[{id, description}]` for all opt-in tools. This prevents future hardcoding drift.
- **`/api/tools` endpoint:** Added to `skills.py`. Returns `AVAILABLE_TOOLS` with descriptions pulled from `TOOL_DEFINITIONS`. Lightweight, no auth required.

### tool_search (meta-tool)

AI self-discovery of available tools.

- **Parameters:** `query` (string)
- **Implementation:** Fuzzy match against tool names and descriptions in `TOOL_DEFINITIONS`
- **Always-on**
- **Response:** Array of `{name, description, parameters_summary}`

### Frontend polish

- Shared widget container CSS component (consistent theming across terminal/light/soft)
- Lazy loading for Chart.js and Leaflet
- Graceful CDN fallbacks

---

## File Changes Summary

### New files
- `tools/__init__.py` — Package init, definitions registry, executor, always-on list
- `tools/memory.py` — memory_edit, conversation_search, recent_chats
- `tools/context.py` — user_time
- `tools/search.py` — web_search, web_fetch, image_search (migrated + new)
- `tools/data.py` — weather, places_search, sports_data
- `tools/widgets.py` — ask_user_input, message_compose, chart_display
- `tools/discovery.py` — tool_search

### Modified files
- `main.py` — Import from tools package, inject always-on tools + memory into system prompt, pass browser timezone, always use tool-use path, emit widget SSE events, pass context to execute_tool
- `skills.py` — Updated AVAILABLE_TOOLS list, ALWAYS_ON_TOOLS handling, new `/api/tools` endpoint
- `static/index.html` — Widget renderer dispatch, lazy CDN loading, widget CSS, timezone in chat requests, ask_user_input auto-send
- `static/skills.html` — Fetch tool list from `/api/tools` instead of hardcoded array

### Removed files
- `tools.py` — Replaced by `tools/` package

---

## External Dependencies

| Dependency | Used By | API Key Required | Fallback |
|------------|---------|-----------------|----------|
| DuckDuckGo HTML | web_search, image_search | No | N/A (existing) |
| Open-Meteo | weather | No | web_search |
| Nominatim/Overpass | places_search | No | Text-only results |
| Google Places | places_search (optional upgrade) | Yes (PLACES_API_KEY) | Nominatim |
| TheSportsDB | sports_data | No (basic) | web_search |
| Chart.js CDN | chart_display frontend | No | Data table |
| Leaflet CDN | places_search frontend | No | Text list + links |

## Testing

The codebase currently has no test infrastructure. At minimum, `memory_edit` needs validation tests since it mutates persistent user state. Recommended: add a `tests/` directory with pytest tests for:
- `memory_edit` — all four commands, limits enforcement, file I/O
- `conversation_search` — keyword matching, result limiting, empty history
- `user_time` — timezone precedence (parameter > context > UTC)
- `calculator` — safety validation (unchanged but should be covered during migration)

Other tools interact with external APIs and are better tested manually or with integration tests.

## Non-Goals

- Google Calendar/Drive integration (requires OAuth, out of scope)
- Device alarms/timers (requires native mobile integration)
- User location via GPS (requires HTTPS + geolocation API permissions)
- End conversation tool (safety tool, not needed for self-hosted)
- Recipe display (niche, can be added later as a community contribution)
