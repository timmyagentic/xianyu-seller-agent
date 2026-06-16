# Xianyu Seller Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, single-process Python MVP that migrates XianyuAutoAgent auto-reply behavior first, then adds shared message parsing, SQLite-backed virtual delivery, and relisting for existing published items.

**Architecture:** Keep the root-level Python entrypoint described in `AGENTS.md`: `main.py`, `XianyuApis.py`, `XianyuAgent.py`, `context_manager.py`, `xianyu_qr_login.py`, `utils/`, and `prompts/`. Add focused service modules under `services/messages/`, `services/delivery/`, and `services/listing/`; use SQLite for all persisted state and dependency injection for platform calls so tests can run without real cookies or accounts.

**Tech Stack:** Python 3, `sqlite3`, `asyncio`, `requests`, `websockets`, `loguru`, `python-dotenv`, `openai`, optional `aiohttp` and `playwright` behind feature boundaries, and `pytest` for tests.

---

## Operating Rules

- Work only in `/Volumes/SamsungDisk/Code/.worktrees/xianyu-seller-agent-mvp` on branch `codex/xianyu-seller-agent-mvp`.
- Keep a draft PR open from the first implementation-planning commit.
- Commit every completed stage separately with Conventional Commit messages.
- Use TDD for production behavior: write the failing test, run it, implement the minimum code, rerun tests, then commit.
- Do not modify `/Volumes/SamsungDisk/Code/XianyuAutoAgent` or `/Volumes/SamsungDisk/Code/xianyu-auto-reply`; read them as references only.
- Do not commit `.env`, cookies, API keys, runtime SQLite databases, buyer data, delivery inventory, screenshots containing sensitive data, or real relist task files.
- Stop platform automation and ask for human handling if real cookies, QR login, slider/risk-control handling, real paid orders, or real relisting clicks are required.

## Stage 0: Project Scaffolding and Safety

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `tests/test_project_safety.py`
- Modify: `README.md`

- [x] **Step 1: Write failing safety tests**

```python
from pathlib import Path


def test_gitignore_protects_runtime_and_secret_files():
    text = Path(".gitignore").read_text(encoding="utf-8")
    for pattern in [".env", "data/", "relist/*.json", "*.db", "*.sqlite", "__pycache__/"]:
        assert pattern in text


def test_expected_project_files_are_declared():
    assert Path("requirements.txt").exists()
    assert Path(".env.example").exists()
    assert Path("pytest.ini").exists()
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_project_safety.py -q`

Expected: fail because `tests/test_project_safety.py`, `.gitignore`, `.env.example`, `requirements.txt`, or `pytest.ini` do not exist yet.

- [x] **Step 3: Add minimal project files**

Create `.gitignore` with runtime and secret exclusions. Create `.env.example` with non-secret defaults for `API_KEY`, `MODEL_BASE_URL`, `COOKIES_STR`, and feature flags set to disabled. Create `requirements.txt` from the XianyuAutoAgent dependency baseline plus `pytest` and optional libraries required by planned services. Create `pytest.ini` with `testpaths = tests`.

- [x] **Step 4: Run safety tests**

Run: `python -m pytest tests/test_project_safety.py -q`

Expected: pass.

- [x] **Step 5: Commit**

```bash
git add .gitignore .env.example requirements.txt pytest.ini tests/test_project_safety.py README.md
git commit -m "chore: scaffold python mvp project"
```

## Stage 1: Auto-Reply Baseline Migration

**Files:**
- Create: `main.py`
- Create: `XianyuApis.py`
- Create: `XianyuAgent.py`
- Create: `context_manager.py`
- Create: `xianyu_qr_login.py`
- Create: `utils/__init__.py`
- Create: `utils/xianyu_utils.py`
- Create: `prompts/classify_prompt_example.txt`
- Create: `prompts/default_prompt_example.txt`
- Create: `prompts/price_prompt_example.txt`
- Create: `prompts/tech_prompt_example.txt`
- Create: `tests/test_context_manager.py`
- Create: `tests/test_agent_routing.py`
- Create: `tests/test_qr_login.py`

- [x] **Step 1: Write failing tests for context storage**

Cover `ChatContextManager` creating `messages`, `chat_bargain_counts`, and `items`; saving and reading item JSON; adding chat messages; and incrementing bargain counts.

- [x] **Step 2: Write failing tests for intent routing and safety filtering**

Cover price, tech, default, and no-reply routing without calling a real LLM by injecting fake agents or monkeypatching the classify call.

- [x] **Step 3: Write failing tests for QR login display helpers**

Cover QR display lines and error classes using test-only fake QR data.

- [x] **Step 4: Run tests to verify failures**

Run: `python -m pytest tests/test_context_manager.py tests/test_agent_routing.py tests/test_qr_login.py -q`

Expected: fail because migrated modules do not exist.

- [x] **Step 5: Migrate and adapt XianyuAutoAgent baseline**

Copy behavior from `/Volumes/SamsungDisk/Code/XianyuAutoAgent` into this repository. Keep `python main.py --qr-login` and `python main.py`. Replace the global `bot` dependency by injecting `XianyuReplyBot` into `XianyuLive`. Keep real platform calls behind normal runtime paths; tests must not require credentials.

- [x] **Step 6: Verify compile and tests**

Run:

```bash
python -m py_compile main.py XianyuApis.py XianyuAgent.py context_manager.py xianyu_qr_login.py utils/xianyu_utils.py
python -m pytest tests/test_context_manager.py tests/test_agent_routing.py tests/test_qr_login.py -q
```

Expected: compile succeeds and tests pass.

- [x] **Step 7: Commit**

```bash
git add main.py XianyuApis.py XianyuAgent.py context_manager.py xianyu_qr_login.py utils prompts tests README.md docs/reference-implementation-map.md
git commit -m "feat: migrate auto reply baseline"
```

## Stage 2: Shared Message Parsing

**Files:**
- Create: `services/__init__.py`
- Create: `services/messages/__init__.py`
- Create: `services/messages/models.py`
- Create: `services/messages/parser.py`
- Create: `services/messages/dedup.py`
- Create: `tests/test_message_parser.py`
- Modify: `main.py`

- [x] **Step 1: Write failing parser tests**

Cover sync package detection, base64/decrypt fallback, normal chat parsing, card update parsing, item ID extraction from reminder URL and extJson, message ID extraction, marketing `MsgTips` filtering, expired message filtering, and own-seller message identification.

- [x] **Step 2: Run parser tests to verify failures**

Run: `python -m pytest tests/test_message_parser.py -q`

Expected: fail because `services.messages` does not exist.

- [x] **Step 3: Implement parser and model**

Create an `IncomingMessage` dataclass with `chat_id`, `item_id`, `sender_id`, `sender_name`, `text`, `message_id`, `message_time`, `raw`, `is_from_self`, and `kind`. Port lightweight parsing behavior from `xianyu-auto-reply/websocket/app/services/xianyu/message_handler.py` without database callbacks.

- [x] **Step 4: Wire parser into `XianyuLive`**

Use the parser in `handle_message` while preserving ACK, heartbeat, token refresh, manual takeover, item cache lookup, context writes, and `send_msg`.

- [x] **Step 5: Verify**

Run:

```bash
python -m py_compile main.py services/messages/models.py services/messages/parser.py services/messages/dedup.py
python -m pytest tests/test_message_parser.py tests/test_context_manager.py tests/test_agent_routing.py -q
```

Expected: pass.

- [x] **Step 6: Commit**

```bash
git add main.py services tests docs/reference-implementation-map.md
git commit -m "feat: add shared message parser"
```

## Stage 3: SQLite Delivery Schema and CLI

**Files:**
- Create: `services/delivery/__init__.py`
- Create: `services/delivery/models.py`
- Create: `services/delivery/store.py`
- Create: `services/delivery/content.py`
- Create: `tests/test_delivery_store.py`
- Create: `tests/test_delivery_content.py`
- Modify: `context_manager.py`
- Modify: `main.py`

- [x] **Step 1: Write failing delivery store tests**

Cover `delivery_configs`, `delivery_inventory`, and `delivery_logs` creation; adding a text config; enabling/disabling config; adding data inventory rows; and listing configs by `item_id`.

- [x] **Step 2: Write failing content tests**

Cover variable replacement for `{order_id}`, `{item_id}`, `{buyer_id}`, `{buyer_name}`, `{item_title}`, `{order_quantity}`, and safe behavior for unknown variables.

- [x] **Step 3: Run tests to verify failures**

Run: `python -m pytest tests/test_delivery_store.py tests/test_delivery_content.py -q`

Expected: fail because delivery modules do not exist.

- [x] **Step 4: Implement delivery store and content rendering**

Use `sqlite3` transactions and explicit status values. Do not add external services. Add CLI handlers for `python main.py delivery add ...` and `python main.py delivery list`.

- [x] **Step 5: Verify**

Run:

```bash
python -m py_compile main.py context_manager.py services/delivery/store.py services/delivery/content.py
python -m pytest tests/test_delivery_store.py tests/test_delivery_content.py -q
python main.py delivery --help
```

Expected: compile succeeds, tests pass, and CLI help prints delivery commands without requiring cookies.

- [x] **Step 6: Commit**

```bash
git add main.py context_manager.py services/delivery tests README.md docs/reference-implementation-map.md
git commit -m "feat: add delivery configuration store"
```

## Stage 4: Idempotent Text and Data Auto-Delivery

**Files:**
- Create: `services/delivery/orders.py`
- Create: `services/delivery/service.py`
- Create: `tests/test_delivery_service.py`
- Modify: `services/delivery/store.py`
- Modify: `main.py`

- [x] **Step 1: Write failing auto-delivery tests**

Cover paid-order trigger parsing, duplicate sent-order skip, text delivery generation, data reservation for quantity 1, data reservation for quantity N, insufficient inventory without partial reservation, send failure preserving reservations as retryable, and retry reusing the same reservation rows.

- [x] **Step 2: Run tests to verify failures**

Run: `python -m pytest tests/test_delivery_service.py -q`

Expected: fail because delivery service behavior is missing.

- [x] **Step 3: Implement service**

Create a `DeliveryService` that accepts a send callback and an order detail provider. Use `delivery_logs` and reservation state for idempotency. Keep auto-delivery disabled unless explicitly enabled by environment or config.

- [x] **Step 4: Wire into card update or paid-order messages**

Stage note: this step establishes the injectable delivery service and safe default-off boundary. Real paid-message order number extraction is completed in Stage 5 before runtime triggering is enabled.

Use `IncomingMessage.kind` and trigger keywords such as `我已付款，等待你发货` and `等待卖家发货`. Do not call real external APIs in tests.

- [x] **Step 5: Verify**

Run:

```bash
python -m py_compile main.py services/delivery/orders.py services/delivery/service.py services/delivery/store.py
python -m pytest tests/test_delivery_service.py tests/test_delivery_store.py tests/test_message_parser.py -q
```

Expected: pass.

- [x] **Step 6: Commit**

```bash
git add main.py services/delivery tests README.md docs/reference-implementation-map.md
git commit -m "feat: implement idempotent virtual delivery"
```

## Stage 5: API Delivery and Order Detail Fetching

**Files:**
- Modify: `XianyuApis.py`
- Modify: `services/delivery/orders.py`
- Modify: `services/delivery/service.py`
- Create: `tests/test_order_detail.py`
- Create: `tests/test_api_delivery.py`

- [x] **Step 1: Write failing order API tests**

Cover `mtop.idle.web.trade.order.detail` request signing data shape, response parsing for quantity, amount, spec, and receiver fields, token-expired retry classification, and Set-Cookie merge behavior using fake responses.

- [x] **Step 2: Write failing API delivery tests**

Cover GET/POST API delivery, JSON response extraction, dynamic parameter replacement, network failure retry, and failure not consuming data inventory.

- [x] **Step 3: Run tests to verify failures**

Run: `python -m pytest tests/test_order_detail.py tests/test_api_delivery.py -q`

Expected: fail because API delivery and order detail provider are incomplete.

- [x] **Step 4: Implement APIs behind injectable HTTP clients**

Adapt from `auto_delivery_handler.py` and `delivery_utils.py` while avoiding Redis, ORM, backend notifications, auto-confirm, and account-closing behavior.

- [x] **Step 5: Verify**

Run:

```bash
python -m py_compile XianyuApis.py services/delivery/orders.py services/delivery/service.py
python -m pytest tests/test_order_detail.py tests/test_api_delivery.py tests/test_delivery_service.py -q
```

Expected: pass.

- [x] **Step 6: Commit**

```bash
git add XianyuApis.py services/delivery tests README.md docs/reference-implementation-map.md
git commit -m "feat: add api delivery and order details"
```

## Stage 6: Existing-Item Relisting

**Files:**
- Create: `services/listing/__init__.py`
- Create: `services/listing/models.py`
- Create: `services/listing/store.py`
- Create: `services/listing/relist.py`
- Create: `services/listing/playwright_relist.py`
- Create: `tests/test_listing_config.py`
- Create: `tests/test_listing_relist.py`
- Modify: `XianyuApis.py`
- Modify: `main.py`

- [x] **Step 1: Write failing listing tests**

Cover relist JSON validation, item ownership validation, `already_active` behavior, API success result parsing, API failure reason mapping, Playwright fallback command construction, and post-success delivery config binding.

- [x] **Step 2: Run tests to verify failures**

Run: `python -m pytest tests/test_listing_config.py tests/test_listing_relist.py -q`

Expected: fail because listing modules do not exist.

- [x] **Step 3: Implement relisting API boundary and local job store**

Create `listing_jobs` persistence. Prefer API path through `XianyuApis` when a known endpoint is configured; otherwise return a structured `manual_required` or `playwright_required` result without pretending relist succeeded.

- [x] **Step 4: Implement Playwright fallback wrapper**

Add cookie injection and safety checks only. Do not bypass slider/risk-control verification. Store screenshot paths only when screenshots are produced by an authorized manual run.

- [x] **Step 5: Add CLI**

Support `python main.py listing relist --item-id 123`, `python main.py listing relist relist/item-001.json`, and `python main.py listing status`.

- [x] **Step 6: Verify**

Run:

```bash
python -m py_compile main.py XianyuApis.py services/listing/store.py services/listing/relist.py services/listing/playwright_relist.py
python -m pytest tests/test_listing_config.py tests/test_listing_relist.py tests/test_delivery_store.py -q
python main.py listing --help
```

Expected: pass and help prints without requiring real cookies.

- [x] **Step 7: Commit**

```bash
git add main.py XianyuApis.py services/listing services/delivery tests README.md docs/reference-implementation-map.md
git commit -m "feat: add existing item relisting"
```

## Stage 7: Documentation, Final Verification, and PR Readiness

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/reference-implementation-map.md`
- Create or modify: focused docs under `docs/` if implementation details require them

- [x] **Step 1: Update docs**

Document install, `.env.example`, QR login, auto-reply run command, delivery CLI, listing CLI, feature flags, fake-test boundary, and manual acceptance requirements.

- [x] **Step 2: Run full local verification**

Run:

```bash
python -m py_compile main.py XianyuApis.py XianyuAgent.py context_manager.py xianyu_qr_login.py utils/xianyu_utils.py services/messages/*.py services/delivery/*.py services/listing/*.py
python -m pytest -q
python main.py --help
python main.py delivery --help
python main.py listing --help
git status -sb
```

Expected: compile succeeds, tests pass, help commands do not require credentials, and git status is clean after final commit.

- [x] **Step 3: Commit**

```bash
git add README.md AGENTS.md docs tests
git commit -m "docs: document mvp operation and verification"
```

- [x] **Step 4: Update draft PR**

Push all commits and update the PR body with changed files, reference sources, validation output, secrets/cookie risk statement, and remaining manual acceptance steps.
