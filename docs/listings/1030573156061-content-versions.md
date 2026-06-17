# Listing content versions for item 1030573156061

This file versions the public title and description for the Xianyu listing so that
future edits can be audited or rolled back without relying on browser history.

## Item

- Item ID: `1030573156061`
- Product: 智谱 GLM coding plan
- Source page: `https://www.goofish.com/publish?itemId=1030573156061&editScene=rePutOn`
- Capture date: 2026-06-17, Asia/Shanghai

## Version policy

- Add a new version before changing the live listing.
- Keep the full first line because the publish form uses the first rich-text line as the listing title.
- Keep the full body text, not only the changed fragment.
- To roll back, open the source page above, replace the rich-text content with the target version, then publish.

## V1 - pre-optimization baseline

Status: superseded by V2 during the 2026-06-17 exposure optimization pass.

```text
智谱 GLM coding plan

智谱 7天体验卡，适合想试试的朋友。需要的直接拍，
新用户才能领，关联到你自己注册的账号。

体验卡支持的模型：
GLM-4.7
GLM-4.6
GLM-4.5-Air

体验卡暂不支持的模型：
GLM-5 / 5.1 / 5.2
GLM-5-turbo

需要直接拍，体验卡发出不退，介意慎拍。有需要可以私聊
```

## V2 - auto-delivery exposure optimization

Status: superseded by V3 during the 2026-06-17 exposure optimization pass.

Rationale:

- Put `自动发货` at the beginning for stronger search-result scanning.
- Add `Coding Plan`, `7天体验卡`, `新用户`, and `GLM-4.7/4.6` in the first line.
- Preserve the model eligibility and refund boundaries from V1.
- Avoid adding a `10分钟发货` promise because the platform-side switch was observed as off.

```text
自动发货｜智谱GLM Coding Plan 7天体验卡｜新用户｜GLM-4.7/4.6

【自动发货】智谱 GLM Coding Plan 7天体验卡，适合想低成本试用 AI 编程能力的新用户。拍下付款后发送领卡/激活链接，关联到你自己注册的智谱账号。

体验卡支持的模型：
GLM-4.7
GLM-4.6
GLM-4.5-Air

体验卡暂不支持的模型：
GLM-5 / 5.1 / 5.2
GLM-5-turbo

新用户才能领。体验卡发出不退，介意慎拍。有需要可以私聊
```

## V3 - trust and conversion wording

Status: published live on 2026-06-17, Asia/Shanghai.

Rationale:

- Keep the V2 search-focused first line so the main keywords stay stable.
- Add stronger conversion wording learned from competitor sampling: official link, not a shared account, instant delivery, account binding, and clear activation steps.
- Preserve the model support boundary and refund boundary.
- Avoid claiming `10分钟发货` because the platform-side switch was observed as off.

```text
自动发货｜智谱GLM Coding Plan 7天体验卡｜新用户｜GLM-4.7/4.6

【自动发货｜官方领卡链接】智谱 GLM Coding Plan 7天体验卡，非共享账号，适合想低成本试用 AI 编程能力的新用户。拍下付款后发送领卡/激活链接，卡片会关联到你自己注册的智谱账号，登录或注册后点击链接即可激活。

体验卡支持的模型：
GLM-4.7
GLM-4.6
GLM-4.5-Air

体验卡暂不支持的模型：
GLM-5 / 5.1 / 5.2
GLM-5-turbo

使用前请确认：仅限未领取过体验卡、未购买过 Coding Plan 套餐的新用户。链接发出即生效，虚拟商品售出不退不换，介意慎拍。有需要可以私聊。
```

## Operational notes

- Runtime evidence from the active MVP worktree showed an enabled text delivery config for this item and `AUTO_DELIVERY_ENABLED=true`.
- Runtime evidence from the active MVP worktree showed an official-domain hint in the text delivery content. The full delivery URL is intentionally not recorded here.
- The live publish form showed `无需邮寄` checked.
- The live publish form showed the platform `10分钟发货` switch off; do not describe the listing as `10分钟发货` unless that setting is explicitly enabled later.
- After submitting V2, the browser landed on `https://www.goofish.com/item?id=1030573156061&categoryId=&spm=a21ybx.publish.0.0`.
- Post-submit page evidence included the V2 first line and body text.
- After submitting V3, the browser landed on `https://www.goofish.com/item?id=1030573156061&categoryId=&spm=a21ybx.publish.0.0`.
- Post-submit page evidence included `【自动发货｜官方领卡链接】`, `非共享账号`, and `链接发出即生效`.
