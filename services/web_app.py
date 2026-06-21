import asyncio
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from XianyuApis import XianyuApis
from services.delivery.store import DeliveryStore
from services.listing.models import PublishRequest
from services.listing.playwright_publish import PlaywrightPublishExecutor
from services.listing.playwright_relist import PlaywrightRelistExecutor, default_relist_management_url
from services.listing.relist import RelistService, load_relist_request
from services.listing.store import ListingStore
from services.review.store import ReviewStore
from utils.xianyu_utils import trans_cookies


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def run_web_server(*, host: str = "127.0.0.1", port: int = 8765, db_path: str = "data/chat_history.db") -> None:
    handler_class = make_handler(db_path=db_path)
    server = ThreadingHTTPServer((host, port), handler_class)
    print(f"xianyu-seller-agent web listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def make_handler(*, db_path: str):
    class WebHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle_get()

        def do_POST(self):
            self._handle_post()

        def log_message(self, format, *args):
            return

        def _handle_get(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/summary":
                self._send_json(summary_payload(db_path))
                return
            if parsed.path == "/api/delivery-configs":
                self._send_json(delivery_configs_payload(db_path))
                return
            if parsed.path == "/api/auto-relist":
                self._send_json(auto_relist_payload(db_path))
                return
            if parsed.path == "/api/listing-jobs":
                query = parse_qs(parsed.query)
                limit = int((query.get("limit") or ["20"])[0])
                self._send_json(listing_jobs_payload(db_path, limit=limit))
                return
            if parsed.path == "/api/items":
                self._send_json(items_payload(db_path))
                return
            self._serve_static(parsed.path)

        def _handle_post(self):
            parsed = urlparse(self.path)
            data = self._read_json()
            if parsed.path == "/api/delivery-configs":
                self._send_json(create_delivery_config(db_path, data))
                return
            if parsed.path == "/api/auto-relist":
                self._send_json(create_auto_relist_config(db_path, data))
                return
            if parsed.path == "/api/relist":
                self._send_json(run_relist(db_path, data))
                return
            if parsed.path == "/api/publish":
                result, status = run_publish(db_path, data)
                self._send_json(result, status=status)
                return
            self._send_json({"success": False, "message": "not found"}, status=404)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}

        def _serve_static(self, path: str):
            if path in ("", "/"):
                path = "/index.html"
            target = (WEB_ROOT / path.lstrip("/")).resolve()
            if WEB_ROOT not in target.parents and target != WEB_ROOT:
                self._send_json({"success": False, "message": "not found"}, status=404)
                return
            if not target.exists() or not target.is_file():
                self._send_json({"success": False, "message": "not found"}, status=404)
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict | list, *, status: int = 200):
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return WebHandler


def summary_payload(db_path: str) -> dict:
    listing_store = ListingStore(db_path=db_path)
    delivery_store = DeliveryStore(db_path=db_path)
    review_store = ReviewStore(db_path=db_path)
    return {
        "success": True,
        "env": {
            "auto_reply_enabled": _env_bool("AUTO_REPLY_ENABLED", True),
            "auto_delivery_enabled": _env_bool("AUTO_DELIVERY_ENABLED", False),
            "auto_confirm_delivery_enabled": _env_bool("AUTO_CONFIRM_DELIVERY_ENABLED", False),
            "auto_relist_enabled": _env_bool("AUTO_RELIST_ENABLED", False),
            "auto_relist_allow_playwright": _env_bool("AUTO_RELIST_ALLOW_PLAYWRIGHT", False),
            "auto_relist_confirm_playwright": _env_bool("AUTO_RELIST_CONFIRM_PLAYWRIGHT", False),
            "auto_review_enabled": _env_bool("AUTO_REVIEW_ENABLED", False),
            "auto_review_confirm_playwright": _env_bool("AUTO_REVIEW_CONFIRM_PLAYWRIGHT", False),
            "cookies_present": bool(os.getenv("COOKIES_STR")),
        },
        "counts": {
            "delivery_configs": len(delivery_store.list_configs()),
            "auto_relist_configs": len(listing_store.list_auto_relist_configs()),
            "review_configs": len(review_store.list_configs()),
            "review_tasks": len(review_store.list_tasks(limit=500)),
            "items": len(listing_store.list_item_snapshots(limit=500)),
            "listing_jobs": len(listing_store.list_jobs(limit=500)),
        },
    }


def delivery_configs_payload(db_path: str) -> dict:
    configs = DeliveryStore(db_path=db_path).list_configs()
    return {
        "success": True,
        "configs": [
            {
                "id": config.id,
                "item_id": config.item_id,
                "name": config.name,
                "delivery_type": config.delivery_type,
                "enabled": config.enabled,
                "content_preview": config.content[:120],
            }
            for config in configs
        ],
    }


def create_delivery_config(db_path: str, data: dict) -> dict:
    store = DeliveryStore(db_path=db_path)
    config_id = store.add_config(
        item_id=str(data.get("item_id") or "").strip(),
        name=str(data.get("name") or data.get("item_id") or "").strip(),
        delivery_type=str(data.get("delivery_type") or "text"),
        content=str(data.get("content") or ""),
        enabled=bool(data.get("enabled", True)),
    )
    return {"success": True, "id": config_id}


def auto_relist_payload(db_path: str) -> dict:
    configs = ListingStore(db_path=db_path).list_auto_relist_configs()
    return {"success": True, "configs": [config.__dict__ for config in configs]}


def create_auto_relist_config(db_path: str, data: dict) -> dict:
    store = ListingStore(db_path=db_path)
    config_id = store.upsert_auto_relist_config(
        item_id=str(data.get("item_id") or "").strip(),
        target_stock=int(data.get("target_stock") or 1),
        expected_title=str(data.get("expected_title") or ""),
        enabled=bool(data.get("enabled", True)),
        allow_playwright=bool(data.get("allow_playwright", False)),
    )
    return {"success": True, "id": config_id}


def listing_jobs_payload(db_path: str, *, limit: int = 20) -> dict:
    jobs = ListingStore(db_path=db_path).list_jobs(limit=max(1, min(limit, 100)))
    return {"success": True, "jobs": [job.__dict__ for job in jobs]}


def items_payload(db_path: str) -> dict:
    items = ListingStore(db_path=db_path).list_item_snapshots(limit=100)
    return {
        "success": True,
        "items": [
            {
                "item_id": item.item_id,
                "title": item.title,
                "status": item.status,
                "item_url": item.item_url,
                "stock": (item.raw or {}).get("stock", ""),
            }
            for item in items
        ],
    }


def run_relist(db_path: str, data: dict) -> dict:
    request = load_relist_request(
        {
            "item_id": data.get("item_id"),
            "expected_title": data.get("expected_title", ""),
            "target_stock": data.get("target_stock"),
        }
    )
    allow_playwright = bool(data.get("allow_playwright"))
    confirm_real_relist = bool(data.get("confirm_real_relist"))
    executor = _build_relist_executor(
        allow_playwright=allow_playwright and confirm_real_relist,
        target_stock=request.target_stock,
    )
    api_client = _build_api_from_env()
    service = RelistService(
        listing_store=ListingStore(db_path=db_path),
        delivery_store=DeliveryStore(db_path=db_path),
        api_client=api_client,
        allow_playwright=allow_playwright,
        relist_executor=executor,
        playwright_required_reason="" if confirm_real_relist else "real_relist_confirmation_required",
    )
    result = asyncio.run(service.relist(request))
    return {"success": result.status == "relisted", "result": result.__dict__}


def run_publish(db_path: str, data: dict) -> tuple[dict, int]:
    if not data.get("confirm_real_publish"):
        return (
            {
                "success": False,
                "failed_reason": "real_publish_confirmation_required",
                "message": "发布新商品需要显式确认",
            },
            400,
        )
    executor = _build_publish_executor()
    if not executor:
        return (
            {
                "success": False,
                "failed_reason": "cookie_missing",
                "message": "缺少 COOKIES_STR",
            },
            400,
        )
    request = PublishRequest(
        title=str(data.get("title") or ""),
        description=str(data.get("description") or ""),
        price=str(data.get("price") or ""),
        stock=int(data.get("stock") or 1),
        images=tuple(str(image) for image in data.get("images", []) if str(image).strip()),
    )
    result = asyncio.run(executor.publish(request))
    if result.success and result.item_id:
        ListingStore(db_path=db_path).save_item_snapshot(
            {
                "item_id": result.item_id,
                "itemId": result.item_id,
                "id": result.item_id,
                "title": request.title,
                "status": "active",
                "item_url": result.item_url,
                "itemUrl": result.item_url,
                "status_source": "publish_result",
                "stock": request.stock,
            }
        )
    return {"success": result.success, "result": result.__dict__}, 200 if result.success else 400


def _build_api_from_env():
    cookies_str = os.getenv("COOKIES_STR", "")
    if not cookies_str:
        return None
    api = XianyuApis()
    api.session.cookies.update(trans_cookies(cookies_str))
    return api


def _build_relist_executor(*, allow_playwright: bool, target_stock: int | None = None):
    cookies_str = os.getenv("COOKIES_STR", "")
    if not allow_playwright or not cookies_str:
        return None
    management_url = os.getenv("AUTO_RELIST_MANAGEMENT_URL", "").strip()
    return PlaywrightRelistExecutor(
        cookies_str=cookies_str,
        headless=_env_bool("AUTO_RELIST_PLAYWRIGHT_HEADLESS", _env_bool("PLAYWRIGHT_HEADLESS", True)),
        screenshot_dir=os.getenv("AUTO_RELIST_SCREENSHOT_DIR", "data/relist-screenshots"),
        management_url=management_url or default_relist_management_url(target_stock),
    )


def _build_publish_executor():
    cookies_str = os.getenv("COOKIES_STR", "")
    if not cookies_str:
        return None
    return PlaywrightPublishExecutor(
        cookies_str=cookies_str,
        headless=_env_bool("AUTO_PUBLISH_PLAYWRIGHT_HEADLESS", _env_bool("PLAYWRIGHT_HEADLESS", True)),
        screenshot_dir=os.getenv("AUTO_PUBLISH_SCREENSHOT_DIR", "data/publish-screenshots"),
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}
