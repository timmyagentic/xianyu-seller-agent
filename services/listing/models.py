from dataclasses import dataclass


@dataclass(frozen=True)
class RelistDeliveryConfig:
    delivery_type: str
    content: str = ""
    name: str = ""
    api_config: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class RelistRequest:
    item_id: str
    expected_title: str = ""
    target_stock: int | None = None
    delivery: RelistDeliveryConfig | None = None


@dataclass(frozen=True)
class AutoRelistConfig:
    id: int
    item_id: str
    target_stock: int
    expected_title: str
    enabled: bool
    allow_playwright: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ItemSnapshot:
    item_id: str
    title: str
    status: str
    item_url: str = ""
    raw: dict | None = None


@dataclass(frozen=True)
class RelistApiResult:
    success: bool
    final_status: str = ""
    item_url: str = ""
    screenshot_path: str = ""
    response_summary: str = ""
    failed_reason: str = ""


@dataclass(frozen=True)
class RelistResult:
    status: str
    item_id: str
    job_id: int | None = None
    target_stock: int | None = None
    previous_status: str = ""
    final_status: str = ""
    item_url: str = ""
    screenshot_path: str = ""
    response_summary: str = ""
    failed_reason: str = ""


@dataclass(frozen=True)
class ListingJob:
    id: int
    task_type: str
    item_id: str
    expected_title: str
    target_stock: int | None
    delivery_config: str
    previous_status: str
    result_status: str
    final_status: str
    item_url: str
    screenshot_path: str
    response_summary: str
    failed_reason: str
    created_at: str
    updated_at: str
