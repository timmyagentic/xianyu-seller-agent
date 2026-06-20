# 闲鱼订单完成后评价队列设计

日期：2026-06-20

## 一句话目标

在成交订单完成后自动创建“待评价”任务，但不自动提交评价。每个商品只维护一条固定五星正向评价文案；人工确认后，程序通过 Playwright 模拟浏览器进入订单评价页、填写五星和文案，并提交。

## 当前事实

仓库已经具备这些可复用基础：

- `main.py` 中的 WebSocket 消息循环、消息解析、自动发货和发货后 hook。
- `services/messages/` 中的订单状态消息解析和去重。
- `services/delivery/` 中的 SQLite 订单幂等日志。
- `services/listing/` 中的 SQLite 任务记录、CLI 管理、Playwright Cookie 注入、登录上下文预热、风控检测、截图证据和结构化失败模式。
- `python main.py web` 的本地管理页面和 JSON API，可作为后续人工确认入口。

这次能力应作为独立小模块接入，不改变自动回复、自动发货、确认发货和重新上架的核心行为。

## 范围

第一版只做：

1. 为每个商品生成或配置一条固定评价文案，默认五星正向评价。
2. 检测到交易完成、待评价或类似订单状态消息时，按订单创建待评价任务。
3. 同一订单只创建一条评价任务，重复消息幂等跳过。
4. 任务创建后停留在 `pending_confirmation`，等待人工确认。
5. 人工通过 CLI 确认后，才启动 Playwright 浏览器执行真实提交；本地 Web 确认作为后续入口。
6. 真实提交只允许单个任务执行，不提供直接批量评价接口。
7. 成功、失败、截图路径、页面证据和失败原因写入 SQLite。

不做：

- 不调用未知评价提交 API。
- 不批量直接评价。
- 不根据买家表现自动生成差评、中评或动态星级。
- 不绕过滑块、验证码、风控或登录失效。
- 不把评价文案写死在代码里；文案必须来自本地商品级配置。
- 不在没有页面确认结果时标记成功。

## 用户体验

商品级配置：

```bash
python main.py review config suggest --item-id 123
python main.py review config set --item-id 123 --content "交易顺利，沟通友好，感谢支持。"
python main.py review config list
```

队列查看：

```bash
python main.py review queue list
python main.py review queue list --item-id 123
```

人工提交：

```bash
python main.py review submit --task-id 1 --confirm-real-review
```

可选预检：

```bash
python main.py review preflight --task-id 1
python main.py review queue set-url --task-id 1 --review-url "https://..."
```

没有 `--confirm-real-review` 时，`submit` 只返回 `real_review_confirmation_required`，不打开浏览器提交。

## 数据模型

新增 `review_configs`：

- `id`
- `item_id`，唯一。
- `content`，固定评价文案。
- `rating`，第一版固定为 `5`，保留字段便于后续扩展。
- `enabled`
- `created_at`
- `updated_at`

新增 `review_tasks`：

- `id`
- `order_id`，唯一。
- `item_id`
- `buyer_id`
- `buyer_name`
- `chat_id`
- `content`
- `rating`
- `status`
- `review_url`
- `screenshot_path`
- `response_summary`
- `evidence_json`
- `failed_reason`
- `created_at`
- `updated_at`
- `submitted_at`

任务状态：

- `pending_confirmation`：已入队，等待人工确认。
- `submitted`：浏览器提交且页面确认成功。
- `skipped_no_config`：商品未启用评价文案，不入待提交队列或只记录跳过。
- `failed_retryable`：登录、页面入口、按钮、确认结果等可重试问题。
- `blocked_risk_control`：检测到滑块、验证码或风控，需要人工处理。

## 入队流程

1. 消息解析层识别交易完成或待评价类订单状态。
2. 提取 `order_id`、`item_id`、`buyer_id`、`buyer_name` 和 `chat_id`。
3. 查询 `review_configs`，商品没有启用配置时跳过并记录原因。
4. 按 `order_id` 幂等 upsert `review_tasks`。
5. 新任务状态为 `pending_confirmation`，内容使用商品级固定文案，评分为 `5`。
6. 入队不调用 Playwright，不提交评价。

第一版不依赖“已发货成功”或“确认发货成功”作为触发条件，只相信平台消息里明确的交易完成、评价入口或待评价语义。无法识别完成状态时不入队。

## 浏览器执行流程

Playwright 执行器放入 `services/review/playwright_review.py`，复用现有浏览器策略：

1. 向 `.goofish.com`、`.taobao.com` 和 `.alipay.com` 注入 `COOKIES_STR`。
2. 先访问闲鱼首页，再访问淘宝登录页初始化登录上下文。
3. 进入订单详情页或任务中保存的评价页。
4. 检测登录页、滑块、验证码、风控、权限不足。
5. 定位评价入口、五星控件、评价文本框和提交按钮。
6. 找不到关键控件时返回结构化失败，不点击提交。
7. 填写五星和固定文案。
8. 点击提交后等待页面确认。
9. 只有出现明确成功提示或任务页面状态变为已评价时，才标记 `submitted`。
10. 保存截图、URL、页面标题、命中标记、控件数量和失败原因。

默认目标 URL 由配置项控制：

- `AUTO_REVIEW_ORDER_URL_TEMPLATE`：可选订单详情页模板，例如包含 `{order_id}` 的 URL。
- `AUTO_REVIEW_SCREENSHOT_DIR=data/review-screenshots`。
- `AUTO_REVIEW_PLAYWRIGHT_HEADLESS=true`，兼容 `PLAYWRIGHT_HEADLESS`。

如果没有可用 URL 模板，第一版允许 CLI 传 `--review-url` 给任务补充评价入口；自动入队仍可先创建待处理任务。

## AI 使用边界

AI 不参与每个订单的临场判断。第一版只在商品级固定评价文案上提供辅助：

- `review config suggest --item-id 123` 根据商品标题、知识库或本地商品信息生成一条候选短评。
- 候选短评必须经人工确认并写入本地配置，才会用于订单任务。
- 入队任务只复制已确认的商品级固定文案。

文案要求：

- 正向、简短、自然。
- 不承诺平台外服务。
- 不暴露卡密、账号、买家隐私或订单信息。
- 不包含诱导好评、返现、联系方式或敏感词。

## 错误处理

结构化失败原因至少包括：

- `cookie_missing`
- `login_required`
- `risk_control`
- `permission_required`
- `review_url_missing`
- `order_not_found`
- `review_entry_not_found`
- `rating_control_not_found`
- `review_textarea_not_found`
- `submit_button_not_found`
- `review_confirmation_missing`
- `real_review_confirmation_required`
- `playwright_unavailable`

遇到 `risk_control`、`login_required` 或 `permission_required` 时不重试刷屏，任务保留证据并等待人工处理。

## 本地 Web 后续入口

第一版 CLI 可先落地；本地 Web 页面可以随后增加“评价队列”页：

- 展示 `pending_confirmation`、`failed_retryable`、`blocked_risk_control` 和 `submitted`。
- 显示商品、订单、买家昵称、评价文案、失败原因和截图链接。
- 每条任务单独点击确认提交。
- 不提供一键批量提交。

## 测试策略

单元测试覆盖：

- 完成/待评价消息识别。
- 未配置商品不入待提交队列。
- 同一订单重复消息只生成一条任务。
- 商品级固定文案复制到任务。
- CLI 参数校验：没有 `--confirm-real-review` 不执行真实提交。
- Playwright fake page：登录/风控停止、找不到入口停止、填写五星和文案、无确认不成功、确认成功才标记提交。
- SQLite schema 向后兼容。

人工验收：

1. 对测试商品配置固定文案。
2. 用模拟完成消息确认任务入队。
3. 对一个真实可评价订单执行 `review preflight`。
4. 人工确认后执行 `review submit --task-id ... --confirm-real-review`。
5. 在闲鱼页面确认评价已提交，并检查本地任务记录和截图。

## 验收标准

- `python -m pytest -q` 通过。
- `python main.py review --help`、`review config --help`、`review queue --help` 和 `review submit --help` 可用。
- 已完成订单消息能创建 `pending_confirmation` 任务。
- 商品未配置评价文案时不会提交也不会进入待提交队列。
- 同一订单不会重复入队。
- 真实提交必须显式确认，且只提交单个任务。
- Playwright 检测到登录、滑块、验证码、风控或页面控件缺失时停止并记录原因。
- 没有页面确认结果时不标记成功。
