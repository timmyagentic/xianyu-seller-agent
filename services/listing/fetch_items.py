from typing import Any

from .store import ListingStore


def sync_published_items(
    *,
    api,
    listing_store: ListingStore,
    page_size: int = 20,
    max_pages: int | None = None,
    myid: str | None = None,
) -> dict[str, Any]:
    result = api.get_all_published_items(page_size=page_size, max_pages=max_pages, myid=myid)
    if not result.get("success"):
        result.setdefault("saved_count", 0)
        result.setdefault("changed_count", 0)
        return result

    items = result.get("items") or []
    saved_count, changed_count = listing_store.save_item_snapshots(items)
    return {
        **result,
        "saved_count": saved_count,
        "changed_count": changed_count,
    }
