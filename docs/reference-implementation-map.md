# 参考实现映射

本项目的功能都应从已有项目迁移或改写，不应凭空实现。实现前先查本文件，确认应参考的源文件和需要裁剪的部分。

## 来源项目定位

| 项目 | 本项目中的角色 | 使用规则 |
| --- | --- | --- |
| `/Volumes/SamsungDisk/Code/XianyuAutoAgent` | 自动回复主基线 | 优先完整迁入，保持行为一致，再做小幅结构整理 |
| `/Volumes/SamsungDisk/Code/xianyu-auto-reply` | 自动发货、重新上架、订单和商品管理参考库 | 只抽业务实现和协议细节，避免带入重后台架构 |

## 自动回复

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 进程入口、WebSocket、ACK、心跳、token 刷新 | `XianyuAutoAgent/main.py` | 已作为第一阶段主骨架迁入；全局 `bot` 依赖已改为 `XianyuLive` 构造注入 |
| 消息解密和基础过滤 | `XianyuAutoAgent/main.py` | 保留 base64/加密双路径、过期消息过滤和系统消息过滤 |
| 商品信息 API | `XianyuAutoAgent/XianyuApis.py` | 保留 token、登录状态检查、商品详情获取；后续扩展订单接口 |
| Cookie 续期和 Set-Cookie 合并 | `xianyu-auto-reply/common/utils/cookie_refresh.py`、`scheduler/app/services/scheduler/login_renew_task.py`、`websocket/app/services/xianyu/cookie_token_manager.py` | 已迁入轻量版 `loginuser.get` 主动续期、Set-Cookie 合并和运行时 Cookie 同步；不迁入密码登录、滑块自动化和数据库调度 |
| LLM 自动回复和意图路由 | `XianyuAutoAgent/XianyuAgent.py` | 保留 `price`、`tech`、`default`、`no_reply` 路由和安全过滤 |
| SQLite 上下文 | `XianyuAutoAgent/context_manager.py` | 保留 `messages`、`chat_bargain_counts`、`items`，新增迁移表 |
| 扫码登录 | `XianyuAutoAgent/xianyu_qr_login.py` | 直接迁入并保持 `python main.py --qr-login` |
| prompt 模板 | `XianyuAutoAgent/prompts/` | 迁入为默认模板，允许用户覆盖非 `_example` 文件 |

## 消息解析增强

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 消息去重和分发 | `xianyu-auto-reply/websocket/app/services/xianyu/message_handler.py` | 已改写为轻量 `services/messages/`，不依赖数据库配置和后台回调 |
| 卡片更新消息 | 同上 | 已保留解析逻辑，后续用于付款状态变更和订单触发 |
| 营销/系统提示过滤 | 同上 | 已保留明确的 `MsgTips` 过滤判断，避免误杀交易消息 |

## 自动发货

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 发货触发、订单幂等、发送重试 | `xianyu-auto-reply/websocket/app/services/xianyu/auto_delivery_handler.py`、`xianyu_async.py`、`auto_reply_service.py` | 已在 `main.py` 中接入 `paid_order` 消息分支，默认受 `AUTO_DELIVERY_ENABLED=false` 保护；订单幂等改写为 SQLite 日志，不迁入 Redis 分布式锁 |
| 内容变量替换 | `xianyu-auto-reply/websocket/app/services/xianyu/delivery_utils.py` | 已保留 `{order_id}`、`{item_id}`、`{buyer_id}` 等变量，并复用于 API 动态参数 |
| 订单详情接口 | `auto_delivery_handler.py` 中 `_fetch_order_detail_from_api` | 已抽到 `services/delivery/orders.py` 并通过 `XianyuApis` 暴露解析和过期判断 helper |
| 发货日志 | `auto_delivery_handler.py` 的 `_record_delivery_log` 思路 | 已落地为 `delivery_logs` 基础表，不接入后台消息日志表 |
| 禁止重复发货 | `can_auto_delivery`、`mark_delivery_sent`、锁相关逻辑 | 已用 `delivery_logs` 的订单发送记录实现幂等跳过 |
| `data` 库存消费 | `auto_delivery_handler.py` 中 `consume_batch_data` 的业务意图 | 已用 SQLite 事务按订单数量预占库存行，发送成功标记 `sent`，失败保留为 `failed_retryable` 并支持同订单重试复用；本地 CLI 支持 `delivery inventory add/list` 管理一次性 key |
| 闲鱼订单侧确认发货 | `shipping/confirm_service.py`、`internal.py`、`auto_delivery_handler.py` 中 `auto_confirm` / `confirm_before_send` / `send_before_confirm` 策略 | 已迁入轻量版无物流确认发货：预设内容发送成功后调用 `mtop.taobao.idle.logistic.consign.dummy`，`ORDER_ALREADY_DELIVERY` 或“已发货成功”按幂等成功处理；失败记录 `platform_confirm_failed` 并返回 `sent_confirm_failed`，不触发发货后自动重新上架；不迁入后台 API 路由、SQLAlchemy 配置和多平台通知 |

暂不迁入：多级代理卡券、亦凡 API、免拼、买家信用拦截、Redis 锁、后台通知。

## 重新上架

当前绑定账号已经开通鱼小铺。迁移参考实现时，普通重新发布保留 `backend-web/app/services/xianyu_publisher.py` 的 `www.goofish.com/publish` 路径作为无库存 fallback；多库存、鱼小铺发布和库存填写优先参考 `common/services/promotion_xianyu_publisher.py` 的 `seller.goofish.com` 发布路径。真实验证到当前可用的商品管理路由是 `seller-item/goods-manage`，可用于查找商品，但售出商品带库存重新发布应走 `seller-item/publish?itemId=...&editScene=rePutOn`；旧的 `#/seller-item` 路由不可作为默认入口。

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 商品同步和归属校验 | `xianyu-auto-reply/common/services/item_service.py`、`common/utils/item_info_manager.py`、`backend-web/app/api/routes/items.py` | 已参考 `fetch_all_items_from_account`、`get_item_list_info` 和 `/items/get-all-from-account` 思路；MVP 通过 `listing fetch-items` 调用 `mtop.idle.web.xyh.item.list` 同步在售商品到本地 SQLite `items` 快照表，并通过 `listing item-status` / `listing relist` 前置 `XianyuApis.get_item_status` 重新查询当前账号状态，未命中在售列表时使用商品详情接口兜底，区分 `active`、`inactive`、`sold`、`relistable` 等状态，不迁入 SQLAlchemy/Redis |
| 商品操作 API 调用模式 | `xianyu-auto-reply/promotion/backend/app/services/item_delete_api_service.py` | 已参考 mtop seller API 的签名、Cookie、`needLoginPC`、Set-Cookie 合并和 token 过期重试模式，落地为 `XIANYU_RELIST_API` 可配置调用边界；未硬编码未知重新上架接口，也不复用删除动作本身 |
| Playwright 兜底浏览器控制 | `xianyu-auto-reply/common/services/promotion_xianyu_publisher.py`、`backend-web/app/services/xianyu_publisher.py` | 已落地 Cookie 域、闲鱼/seller 首页 -> 淘宝登录页 -> 目标页三段登录上下文预热；无目标库存的普通重新发布使用 `www.goofish.com/publish?itemId=...&editScene=rePutOn`，带目标库存时默认使用 `seller.goofish.com/?site=COMMONPRO#/seller-item/publish?itemId=...&editScene=rePutOn`；商品管理排查可通过 `AUTO_RELIST_MANAGEMENT_URL` 指向 `seller-item/goods-manage`，但不能把商品管理页的普通“发布”误判为重新上架；保留库存输入选择器、登录/滑块/验证码/风控检测、`listing relist-preflight` 只读页面预检和授权浏览器重新上架执行器；目标库存存在但页面没有库存输入框或填入后无法校验目标值时返回 `stock_input_not_found`，不点击发布；preflight 会输出 URL、标题、状态标记和元素数量等安全页面证据，不输出完整页面正文；CLI 真实点击必须同时传入 `--allow-playwright --confirm-real-relist`；发货后后台 hook 不传 `target_stock`，避免鱼小铺多库存商品每次发货后重新提交发布页；只有页面确认成功后才记录 `relisted` |
| 商品管理数量/状态判断 | `promotion/backend/app/services/publish_rule_scheduler.py`、`common/services/item_service.py` | 已基于商品快照状态、标题和 `item_id` 回查做 `already_active`、标题不匹配和归属失败判断 |
| 目标库存字段 | `common/services/promotion_xianyu_publisher.py`、`promotion/backend/app/services/publish_rule_scheduler.py` | 已参考发布流程的 `stock` 字段，把重新上架目标库存保存为 `target_stock`；手动 `listing relist --stock`、preflight 和可注入 API 边界会传递该字段，Playwright 路径必须真实找到库存输入框才会点击发布，否则记录 `stock_input_not_found`；发货后自动重新上架配置保留该字段用于本地策略和审计，但后台 hook 不把它传给平台动作 |
| 上架后绑定发货内容 | `promotion/backend/app/services/publish_coupon_card_service.py` | 已改为 upsert 本地 `delivery_configs`，重新上架成功或已处于上架状态后绑定目标 `item_id` |

## 成交后评价

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 自动评价配置和固定文案 | `xianyu-auto-reply/common/models/auto_rate_config.py`、`backend-web/app/api/routes/auto_rate.py` | 已改为本地 `review_configs`，只支持商品级固定五星正向文案；不迁入多账号配置、用户权限、FastAPI 路由和 API 文案来源 |
| 可评价订单识别和补评价批处理 | `xianyu-auto-reply/scheduler/app/services/scheduler/rate_task.py`、`common/services/order_service.py` | 已改写为运行时监听“交易成功/待评价/评价买家”和评价提醒消息，按 `order_id` 幂等写入 `review_tasks`；提醒消息缺少订单号时从最新成功发货日志回查；不迁入 MySQL 订单表、调度器和批量补评价任务 |
| 评价提交 | `xianyu-auto-reply/common/services/rate_service.py`、`websocket/app/services/xianyu/rate_service.py` | 参考其评价内容、待评价状态和令牌刷新思路，但不迁入 `mtop.taobao.idle.rate.create` 直接评价接口；本项目继续使用 Playwright 浏览器路径，必须检测到真实评价入口、五星控件、文本框、提交按钮和页面确认后才标记 `submitted` |
| 自动触发边界 | `xianyu-auto-reply/scheduler/app/services/scheduler/rate_task.py` | 已新增轻量运行时自动评价：`AUTO_REVIEW_ENABLED=true` 且 `AUTO_REVIEW_CONFIRM_PLAYWRIGHT=true` 时，评价任务入队后自动调用浏览器提交；没有 `review_url` 且没有包含 `{order_id}` 的 `AUTO_REVIEW_ORDER_URL_TEMPLATE` 时保持 `pending_confirmation`，不打开浏览器试错 |

## 发布新商品

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 发布页登录上下文预热 | `xianyu-auto-reply/backend-web/app/services/xianyu_publisher.py`、`common/services/promotion_xianyu_publisher.py` | 普通发布保留闲鱼首页 -> 淘宝登录页 -> `www.goofish.com/publish` 三段跳转；鱼小铺发布可通过 `AUTO_PUBLISH_URL=https://seller.goofish.com/?site=COMMONPRO#/seller-item/publish` 启用 seller 发布页 |
| 发布页字段填写 | `xianyu-auto-reply/common/services/promotion_xianyu_publisher.py`、`backend-web/app/services/xianyu_publisher.py` | 已迁入标题、描述、价格、库存、图片和发布按钮定位策略；不迁入素材库、地址池、分类兜底、返佣选品和后台批量调度 |
| 发布结果确认 | `backend-web/app/services/xianyu_publisher.py` | 已参考跳转商品详情页、页面成功提示和失败提示判断；没有平台确认时返回 `publish_confirmation_missing`，不伪造成功 |

## 本地前端

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 管理台信息架构 | `xianyu-auto-reply/promotion/frontend/src/App.tsx`、`src/config/navigation.ts` | 已新增轻量本地管理页面，包含总览、自动发货、自动上架、发布商品和任务记录；不迁入 React/Vite 依赖、登录系统、用户权限、MySQL/Redis/FastAPI 后台 |
| 管理台 API | `xianyu-auto-reply/promotion/backend/app/api/routes/*` | 已用 Python 标准库 HTTP server 提供本地 JSON API，复用 SQLite store 和现有执行器；真实发布和真实重新上架都必须显式确认 |

MVP 重新上架的目标是“对一个已经发布过、仍能在商品管理中找到的商品执行重新上架”。当前实现已完成本地任务记录、真实状态刷新、归属校验、已上架幂等跳过、目标库存记录、API 结果解析边界、可配置 mtop 重新上架调用、授权 Playwright 执行器和发货配置绑定。发货后自动重新上架由 `AUTO_RELIST_ENABLED` 和商品级 `auto_relist_configs` 同时控制，并会复用运行中的 `XianyuApis` 先刷新当前状态；后台 hook 不传递配置里的 `target_stock`，因此鱼小铺多库存商品仍处于 `active` 时会记录 `already_active`，不会重新提交发布页或修改商品信息。无论 mtop 还是 Playwright 路径，都必须记录前置状态、动作结果、最终商品状态和截图或响应摘要；手动带库存任务还必须记录目标库存。动作确认成功后会再尝试刷新单商品真实状态，并把执行请求、执行前状态、动作来源、Playwright 页面证据和执行后状态写入 `listing_jobs.evidence_json`，同时更新本地快照、`listing_jobs.final_status` 和响应摘要；遇到登录、滑块、验证码、风控、找不到按钮或缺少页面确认时只记录结构化失败，不绕过也不误报成功。

暂不迁入：素材库后台、发布规则定时器、返佣选品、发布删除规则、用户权限、React/Vite 构建链路和重后台服务。

## 后续实现约束

1. 每新增一个功能，先在本文件补充参考来源。
2. 迁移代码时保留关键协议字段、错误判断和日志语义。
3. 删除或替换重项目依赖时，要在 PR 描述中说明替换方式。
4. 如果参考项目中已有测试，优先迁移测试意图；没有测试时补最小单元测试。
5. 文档、README 和实际 CLI 命令必须同步更新。
