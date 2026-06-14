# xianyu-seller-agent MVP 设计

日期：2026-06-14

## 一句话目标

以 `XianyuAutoAgent` 的自动回复为核心骨架，选择性整合 `xianyu-auto-reply` 中已经存在的自动发货、商品管理、重新上架和订单处理能力，形成一个轻量本地卖家自动化 Agent。

## 当前事实

本仓库当前只有文档，尚未迁入代码。后续实现不应从零设计功能，而应围绕两个参考项目重组：

- `XianyuAutoAgent`：当前项目的主来源。它已经具备自动回复需要的登录、WebSocket、消息解密、商品信息、SQLite 上下文、意图路由、人工接管和回复发送。
- `xianyu-auto-reply`：功能参考库。它已经实现更完整的消息解析、自动发货、订单详情、发货锁、商品同步、商品操作 API、发布器、发布后回写和建卡逻辑，但架构过重，只能抽取局部能力。

## 架构原则

1. 先保持 `XianyuAutoAgent` 的单进程 Python 形态。
2. 只使用 SQLite、本地文件和 CLI，不引入 Web 后台、MySQL、Redis 或多服务编排。
3. 迁移功能时保留协议细节和业务判断，替换掉重项目里的 ORM、后台 API、分布式锁和前端依赖。
4. 高风险动作默认关闭；失败要有原因、日志和可重试状态。
5. 不自动绕过平台风控、滑块验证或 Cookie 失效。

## 自动回复基线

自动回复必须首先完整参考 `XianyuAutoAgent`：

1. `main.py` 中 `XianyuLive` 负责 Cookie 初始化、WebSocket 注册、ACK、心跳、token 刷新和消息循环。
2. 收到同步包后尝试 base64/加密解码，过滤输入状态、系统消息、过期消息和无商品 ID 消息。
3. 从消息里解析 `chat_id`、`item_id`、买家 ID、买家昵称和消息文本。
4. 卖家自己发送切换关键词时进入或退出人工接管；卖家普通消息写入上下文。
5. 对买家消息先读取商品缓存，缓存缺失时通过 `XianyuApis.get_item_info` 拉取并保存。
6. `context_manager.py` 维护 `messages`、`chat_bargain_counts` 和 `items`。
7. `XianyuAgent.py` 用规则和 LLM 分类到 `price`、`tech`、`default` 或 `no_reply`。
8. 生成回复后写入上下文，价格意图增加议价次数，再通过 `send_msg` 发送。

迁入时需要修掉一个结构债：不要继续依赖全局 `bot`，应把 `XianyuReplyBot` 注入 `XianyuLive`。

## 自动发货设计

自动发货参考 `xianyu-auto-reply/websocket/app/services/xianyu/auto_delivery_handler.py` 和 `delivery_utils.py`，但落地为轻量 SQLite 服务。

MVP 支持虚拟商品发货：

- `text`：固定文本。
- `data`：一次性库存行。必须先在 SQLite 事务中按订单唯一预占一行库存，发送成功后标记 `sent`；发送失败时保留为 `reserved` 或 `failed_retryable`，由同一订单重试继续使用原预占行或人工释放。
- `api`：调用外部接口取货，失败不消费库存。

触发来源优先使用订单状态消息，例如“我已付款，等待你发货”“等待卖家发货”。后续可增加待发货订单轮询作为补偿。

发货流程：

1. 从消息或卡片更新中解析订单号、买家、商品 ID 和会话 ID。
2. 检查 `delivery_logs`，同一订单已有 `sent` 记录则跳过。
3. 拉取或补全订单详情，包括规格、数量和收货信息。
4. 按商品 ID 匹配启用的 `delivery_configs`。
5. 如果配置类型是 `data`，在同一个 SQLite 事务里为当前订单预占一条 `available` 库存行；同一订单已有预占行时复用，其他订单不能再读取该行。
6. 生成发货内容并替换变量，如 `{order_id}`、`{item_id}`、`{buyer_id}`。
7. 通过现有 WebSocket 会话发送给买家。
8. 发送成功后把预占库存标记为 `sent`；发送失败时写入可重试状态，不把同一库存行发给其他订单。
9. 成功或失败都写入 `delivery_logs`。

发货确认、免拼、图片卡券、多账号分布式锁可以作为后续增强，不进入第一版。

## 重新上架设计

重新上架只针对“已经发布过的商品”。MVP 不从本地草稿创建全新商品，也不上传图片或重填完整发布表单。后续实现应优先寻找并封装闲鱼商品管理的重新上架 API；如果 API 不稳定，再用 Playwright 进入商品管理页，对指定 `item_id` 执行页面上的“重新上架”动作。

输入为本地重新上架配置，最小形式是商品 ID：

```json
{
  "item_id": "1234567890",
  "expected_title": "用于人工核对的商品标题",
  "delivery": {
    "type": "text",
    "content": "发货内容"
  }
}
```

重新上架流程：

1. 校验 `item_id`、可选标题和发货配置。
2. 同步或读取当前账号的商品列表，确认该商品属于当前账号且仍在商品管理中可见。
3. 查询目标商品当前状态；如果已上架，记录为 `already_active`，只刷新发货绑定。
4. 如果已下架或可重新上架，优先调用商品管理 mtop API 执行重新上架。
5. 如果 API 不可用，启动 Playwright Chromium，向 `goofish.com`、`taobao.com`、`alipay.com` 和 `seller.goofish.com` 注入 Cookie。
6. 打开商品管理页，定位目标 `item_id` 或标题，检查登录状态、滑块验证和操作按钮。
7. 点击“重新上架”并等待结果；遇到风控、滑块、无法定位商品或按钮缺失时停止自动动作并记录原因。
8. 重新同步商品状态，记录响应摘要、截图、商品 URL、最终状态和失败原因。
9. 重新上架成功或商品已处于上架状态后，绑定或更新 `delivery_configs.item_id`。

## SQLite 数据模型

沿用自动回复表：

- `messages`
- `chat_bargain_counts`
- `items`

新增表：

- `delivery_configs`：商品 ID、名称、类型、内容、启用状态、创建和更新时间。
- `delivery_inventory`：发货配置、库存内容、状态、预占订单、预占时间、发送时间、失败原因。`reserved_order_no` 应有唯一约束，避免同一订单重复预占；库存行状态更新必须在事务中完成。
- `delivery_logs`：订单号、会话、商品、买家、配置、内容摘要、状态、失败原因。
- `listing_jobs`：任务类型、商品 ID、预期标题、发货配置、前置状态、结果状态、商品 URL、截图路径、响应摘要、失败原因。

所有迁移应由 `context_manager.py` 或独立 SQLite 初始化模块统一执行。

## 实施阶段

1. 迁入 `XianyuAutoAgent` 自动回复，保持 `python main.py` 可运行。
2. 抽出消息解析对象 `IncomingMessage`，让自动回复和自动发货共享。
3. 增加 SQLite 发货配置和发货日志。
4. 实现 `text` 和 `data` 自动发货，并加订单幂等保护。
5. 增加 `api` 发货和订单详情补全。
6. 实现已发布商品重新上架的 API 路径或 Playwright 兜底路径。
7. 重新上架成功或确认已上架后自动绑定发货配置。

## 测试策略

- 自动回复：QR 登录、消息过滤、人工接管、意图路由、安全过滤。
- 自动发货：订单解析、重复订单跳过、库存预占事务、并发订单不重复发同一库存行、发送失败可重试、API 失败不消费、发送失败日志。
- 重新上架：配置校验、商品归属校验、状态转换、Cookie 注入参数、失败原因映射。
- Playwright 真实重新上架需要人工账号和手动验收，不作为默认 CI。

## 验收标准

第一版验收不是“功能都写完”，而是链路可信：

- `python main.py` 能完成自动回复。
- 虚拟商品付款消息能触发一次且仅一次发货。
- 指定已发布过的商品能重新上架，或在已上架时幂等跳过，并记录可追踪结果。
- 文档中的参考来源、命令、数据表和风险边界与代码一致。
