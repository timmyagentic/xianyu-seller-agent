# xianyu-seller-agent MVP 设计

日期：2026-06-14

## 一句话目标

以 `XianyuAutoAgent` 的自动回复为核心骨架，选择性整合 `xianyu-auto-reply` 中已经存在的自动发货、商品发布和订单处理能力，形成一个轻量本地卖家自动化 Agent。

## 当前事实

本仓库当前只有文档，尚未迁入代码。后续实现不应从零设计功能，而应围绕两个参考项目重组：

- `XianyuAutoAgent`：当前项目的主来源。它已经具备自动回复需要的登录、WebSocket、消息解密、商品信息、SQLite 上下文、意图路由、人工接管和回复发送。
- `xianyu-auto-reply`：功能参考库。它已经实现更完整的消息解析、自动发货、订单详情、发货锁、发布器、发布后回写和建卡逻辑，但架构过重，只能抽取局部能力。

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
- `data`：一次性库存行，发送成功后消费。
- `api`：调用外部接口取货，失败不消费库存。

触发来源优先使用订单状态消息，例如“我已付款，等待你发货”“等待卖家发货”。后续可增加待发货订单轮询作为补偿。

发货流程：

1. 从消息或卡片更新中解析订单号、买家、商品 ID 和会话 ID。
2. 检查 `delivery_logs`，同一订单已有 `sent` 记录则跳过。
3. 拉取或补全订单详情，包括规格、数量和收货信息。
4. 按商品 ID 匹配启用的 `delivery_configs`。
5. 生成发货内容并替换变量，如 `{order_id}`、`{item_id}`、`{buyer_id}`。
6. 通过现有 WebSocket 会话发送给买家。
7. 成功或失败都写入 `delivery_logs`。

发货确认、免拼、图片卡券、多账号分布式锁可以作为后续增强，不进入第一版。

## 自动上架设计

自动上架参考 `xianyu-auto-reply/backend-web/app/services/xianyu_publisher.py`、`common/services/promotion_xianyu_publisher.py` 和发布执行服务。MVP 只做单品发布。

输入为本地草稿：

```json
{
  "title": "商品标题",
  "description": "商品描述",
  "price": 99.0,
  "stock": 1,
  "images": ["./assets/listing/item-1.jpg"],
  "delivery": {
    "type": "text",
    "content": "发货内容"
  }
}
```

发布流程：

1. 校验草稿和图片路径。
2. 如果包含 `delivery`，先写入或准备发货配置。
3. 启动 Playwright Chromium。
4. 向 `goofish.com`、`taobao.com`、`alipay.com` 注入 Cookie。
5. 打开闲鱼发布页或卖家发布页。
6. 检查登录状态、滑块验证和发布表单是否渲染。
7. 上传图片，填写描述、价格、库存、所在地和包邮设置。
8. 点击发布，记录 URL、商品 ID、截图或失败原因。
9. 发布成功后绑定 `delivery_configs.item_id`。

## SQLite 数据模型

沿用自动回复表：

- `messages`
- `chat_bargain_counts`
- `items`

新增表：

- `delivery_configs`：商品 ID、名称、类型、内容、启用状态、创建和更新时间。
- `delivery_logs`：订单号、会话、商品、买家、配置、内容摘要、状态、失败原因。
- `listing_drafts`：标题、描述、价格、库存、图片 JSON、发货配置、发布状态、商品 ID、URL、失败原因。

所有迁移应由 `context_manager.py` 或独立 SQLite 初始化模块统一执行。

## 实施阶段

1. 迁入 `XianyuAutoAgent` 自动回复，保持 `python main.py` 可运行。
2. 抽出消息解析对象 `IncomingMessage`，让自动回复和自动发货共享。
3. 增加 SQLite 发货配置和发货日志。
4. 实现 `text` 和 `data` 自动发货，并加订单幂等保护。
5. 增加 `api` 发货和订单详情补全。
6. 引入 Playwright 单品发布。
7. 发布成功后自动绑定发货配置。

## 测试策略

- 自动回复：QR 登录、消息过滤、人工接管、意图路由、安全过滤。
- 自动发货：订单解析、重复订单跳过、库存消费事务、API 失败不消费、发送失败日志。
- 自动上架：草稿校验、图片路径解析、字段映射、Cookie 注入参数。
- Playwright 真实发布需要人工账号和手动验收，不作为默认 CI。

## 验收标准

第一版验收不是“功能都写完”，而是链路可信：

- `python main.py` 能完成自动回复。
- 虚拟商品付款消息能触发一次且仅一次发货。
- 本地草稿能发布单个商品，并记录可追踪结果。
- 文档中的参考来源、命令、数据表和风险边界与代码一致。
