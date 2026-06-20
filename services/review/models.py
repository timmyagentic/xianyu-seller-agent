from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewConfig:
    id: int
    item_id: str
    content: str
    rating: int
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ReviewTask:
    id: int
    order_id: str
    item_id: str
    buyer_id: str
    buyer_name: str
    chat_id: str
    content: str
    rating: int
    status: str
    review_url: str
    screenshot_path: str
    response_summary: str
    evidence_json: str
    failed_reason: str
    created_at: str
    updated_at: str
    submitted_at: str | None


@dataclass(frozen=True)
class ReviewSubmissionRequest:
    task_id: int
    order_id: str
    item_id: str
    review_url: str
    content: str
    rating: int = 5


@dataclass(frozen=True)
class ReviewSubmissionResult:
    success: bool
    status: str = ""
    screenshot_path: str = ""
    response_summary: str = ""
    failed_reason: str = ""
    evidence: dict | None = None
