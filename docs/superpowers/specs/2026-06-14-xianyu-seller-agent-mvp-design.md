# xianyu-seller-agent MVP 设计

日期：2026-06-14

## 背景

当前仓库来自 `XianyuAutoAgent`，已经实现了一个可运行的闲鱼自动回复机器人：通过 Cookie 或扫码登录获取身份，连接闲鱼 WebSocket，接收买家消息，读取商品信息，结合 SQLite 中的会话上下文调用 LLM 生成回复。

另一个项目 `xianyu-auto-reply` 已经覆盖账号管理、自动回复、自动发货、商品发布、订单、评价、返佣和前端后台，但整体太重。新项目不应该复制它的服务拆分和后台体系，而应该抽取其中能服务 MVP 的业务逻辑。

## 产品目标

MVP 只完成一个轻量卖家自动化闭环：

1. 有买家咨询时自动回复。
2. 买家付款后自动发送虚拟商品内容。
3. 卖家可以从本地草稿自动发布商品。

成功标准是：一个普通个人卖家可以在本机或一台小服务器上运行单个 Python 项目，不依赖 MySQL、Redis、前端后台，也能完成自动接待、虚拟商品交付和单品上架。

## 非目标

以下能力不进入 MVP：

- 多租户 SaaS、用户权限、团队协作。
- React 管理后台。
- 返佣、分销、结算、余额和代理订单。
- 商品采集、选品规则、自动删除规则。
- 大规模多账号调度。
- 自动绕过滑块验证或其他平台风控。

## 总体架构

保持单进程 Python 架构，按服务模块拆分职责。

```text
main.py
  ├─ XianyuLive               # WebSocket 连接、消息分发、心跳、重连
  ├─ XianyuReplyBot           # 自动回复
  ├─ ChatContextManager       # SQLite 持久化
  ├─ DeliveryService          # 自动发货
  └─ ListingService           # 自动上架
```

SQLite 是 MVP 的唯一持久化存储。`.env` 管理运行配置，`data/` 存放数据库和运行时文件，`configs/` 或 `catalog/` 存放商品草稿和发货配置。

## 数据模型

现有表：

- `messages`：会话消息历史。
- `chat_bargain_counts`：按会话统计议价次数。
- `items`：商品详情缓存。

MVP 新增表：

- `delivery_configs`
  - `id`
  - `item_id`
  - `name`
  - `type`: `text`、`data`、`api`
  - `content`
  - `enabled`
  - `created_at`
  - `updated_at`

- `delivery_logs`
  - `id`
  - `order_no`
  - `chat_id`
  - `item_id`
  - `buyer_id`
  - `delivery_config_id`
  - `content_preview`
  - `status`: `pending`、`sent`、`failed`、`skipped`
  - `fail_reason`
  - `created_at`
  - `updated_at`

- `listing_drafts`
  - `id`
  - `title`
  - `description`
  - `price`
  - `stock`
  - `images_json`
  - `delivery_config_id`
  - `status`: `draft`、`publishing`、`published`、`failed`
  - `published_item_id`
  - `published_url`
  - `fail_reason`
  - `created_at`
  - `updated_at`

## 自动回复设计

自动回复沿用当前实现，不做大改：

1. WebSocket 收到聊天消息。
2. 过滤系统消息、过期消息、输入状态和卖家自己发出的控制消息。
3. 根据商品 ID 读取或拉取商品信息。
4. 读取会话历史，调用 `XianyuReplyBot.generate_reply`。
5. 如果分类结果是 `no_reply`，跳过回复。
6. 否则发送文本回复并写入上下文。

需要在后续整理中做两处小改：

- 去掉全局 `bot` 依赖，把 `XianyuReplyBot` 注入到 `XianyuLive` 实例。
- 把消息解析结果封装成 `IncomingMessage`，供自动回复和自动发货共享。

## 自动发货设计

### 触发来源

MVP 支持两种触发方式：

1. 实时触发：WebSocket 收到订单状态消息，例如“等待卖家发货”。
2. 补偿触发：定时轮询待发货订单，防止实时消息漏掉。

第一阶段优先实现实时触发，补偿轮询作为第二阶段。

### 发货流程

1. 从订单消息中解析 `order_no`、`item_id`、`buyer_id`、`chat_id`。
2. 如果 `delivery_logs` 已存在同一 `order_no` 的 `sent` 记录，直接跳过。
3. 拉取订单详情，补全规格、数量和收货信息。
4. 按 `item_id` 匹配启用的 `delivery_configs`。
5. 根据配置生成发货内容：
   - `text`：直接发送配置文本。
   - `data`：从库存内容中消费一行，并在同一事务内写回剩余库存。
   - `api`：调用外部接口获取内容，带超时和重试。
6. 通过现有 WebSocket `send_msg` 发给买家。
7. 写入 `delivery_logs`。
8. 如果发送失败，记录失败原因，不重复盲目发送。

### 风险控制

- 默认只支持虚拟商品内容发送，不默认确认平台发货。
- 同一订单必须幂等，只能成功发货一次。
- 没有配置发货内容时跳过并记录。
- `data` 类型必须用事务锁保护，避免并发重复发同一条卡密。
- API 取货失败不能消费库存。
- 触发风控或 Cookie 失效时停止自动动作，要求人工处理。

## 自动上架设计

### 输入形式

MVP 使用本地草稿文件或 SQLite 草稿，不先做后台页面。推荐草稿字段：

```json
{
  "title": "商品标题",
  "description": "商品描述",
  "price": 99.0,
  "stock": 1,
  "images": ["./assets/example-1.jpg"],
  "delivery": {
    "type": "text",
    "content": "发货内容"
  }
}
```

### 发布流程

1. 读取草稿并校验必填字段。
2. 如草稿包含发货配置，先写入 `delivery_configs`。
3. 启动 Playwright Chromium。
4. 注入 `COOKIES_STR` 到 `goofish.com`、`taobao.com`、`alipay.com` 域。
5. 打开闲鱼发布页。
6. 等待表单渲染，检查是否跳转登录或出现滑块验证。
7. 上传图片，填写描述、价格、库存、地址和包邮设置。
8. 点击发布，解析发布后的商品 ID 或 URL。
9. 更新 `listing_drafts` 状态。

### 参考实现取舍

`xianyu-auto-reply` 的 Playwright 发布器有成熟的页面步骤：注入 Cookie、访问发布页、上传图片、等待分类识别、填写描述、价格、库存、地址、包邮并点击发布。MVP 可以参考这些步骤，但不要引入它的后端加载器、前端静态资源、批量发布状态服务和返佣专用页面。

## CLI 设计

MVP 先提供命令行，不做 Web UI。

```bash
python main.py --qr-login
python main.py run
python main.py delivery add --item-id 123 --type text --content "..."
python main.py listing publish drafts/item-001.json
python main.py listing status
```

当前入口只有 `python main.py` 和 `--qr-login`。后续应改为 `argparse` 子命令，同时保持 `python main.py` 兼容为 `python main.py run`。

## 配置

`.env` 保留现有配置：

- `API_KEY`
- `MODEL_BASE_URL`
- `MODEL_NAME`
- `COOKIES_STR`
- `TOGGLE_KEYWORDS`
- `SIMULATE_HUMAN_TYPING`

新增建议配置：

- `AUTO_DELIVERY_ENABLED=False`
- `AUTO_LISTING_HEADLESS=True`
- `DELIVERY_API_TIMEOUT=10`
- `DELIVERY_API_RETRIES=3`
- `LISTING_DEFAULT_ADDRESS=`
- `LISTING_IMAGE_DIR=assets/listing`

默认关闭自动发货，避免用户未配置好就执行高风险动作。

## 实施阶段

### 阶段 1：项目整理和文档

- 更名为 `xianyu-seller-agent`。
- 新建本地目录 `/Volumes/SamsungDisk/Code/xianyu-seller-agent`。
- 更新 README 和 MVP 设计文档。
- 保持当前自动回复可运行。

### 阶段 2：自动发货核心

- 新增 SQLite 表和迁移初始化。
- 新增 `DeliveryConfig`、`DeliveryLog` 数据访问层。
- 抽象订单消息解析。
- 实现 `text` 和 `data` 类型发货。
- 增加订单幂等保护和日志。

### 阶段 3：自动发货增强

- 实现 `api` 类型发货。
- 增加待发货订单轮询补偿。
- 增加发货失败重试策略，但禁止对已成功订单重复发送。
- 增加单元测试覆盖库存消费、幂等和 API 失败。

### 阶段 4：自动上架核心

- 引入 Playwright 依赖。
- 新增草稿校验和发布命令。
- 实现单品发布器。
- 记录发布结果和失败截图。

### 阶段 5：体验整理

- 整理 CLI 帮助文案。
- 提供示例草稿和示例发货配置。
- 增加运行诊断命令。
- 再评估是否需要极简本地 Web UI。

## 测试策略

- 自动回复：保留现有 QR 登录单测，增加意图路由和安全过滤测试。
- 自动发货：用伪订单消息测试触发、幂等、库存消费、API 失败和发送失败。
- 自动上架：把 Playwright 操作封装为小方法，单测校验草稿解析和字段映射；真实发布需要人工账号和沙盒商品，作为手动验收。
- 数据库：用临时 SQLite 文件跑迁移和 DAO 测试。

## 验收标准

MVP 完成时应满足：

1. `python main.py run` 可以启动现有自动回复。
2. 配置某个商品的 `text` 发货内容后，订单触发时只发送一次。
3. 配置某个商品的 `data` 发货内容后，每个订单消费一条库存。
4. 发货结果可在 SQLite 中查询。
5. 给定一个本地商品草稿，可以自动发布单个商品并记录结果。
6. Cookie 失效、滑块验证、接口失败都有明确日志，不静默失败。
