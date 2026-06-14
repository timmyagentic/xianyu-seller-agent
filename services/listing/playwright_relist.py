from dataclasses import dataclass


SELLER_MANAGEMENT_URL = "https://seller.goofish.com/?site=COMMONPRO#/seller-item"
COOKIE_DOMAINS = (".goofish.com", ".taobao.com", ".alipay.com", ".seller.goofish.com")


@dataclass(frozen=True)
class PlaywrightRelistCommand:
    item_id: str
    expected_title: str
    management_url: str
    cookie_domains: tuple[str, ...]


def build_playwright_relist_command(
    *,
    item_id: str,
    expected_title: str = "",
    management_url: str = SELLER_MANAGEMENT_URL,
) -> PlaywrightRelistCommand:
    return PlaywrightRelistCommand(
        item_id=str(item_id),
        expected_title=str(expected_title or ""),
        management_url=management_url,
        cookie_domains=COOKIE_DOMAINS,
    )
