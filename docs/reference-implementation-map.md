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
| 发货触发、订单幂等、发送重试 | `xianyu-auto-reply/websocket/app/services/xianyu/auto_delivery_handler.py` | 改写为 SQLite + 本地锁；不迁入 Redis 分布式锁 |
| 内容变量替换 | `xianyu-auto-reply/websocket/app/services/xianyu/delivery_utils.py` | 已保留 `{order_id}`、`{item_id}`、`{buyer_id}` 等变量，并复用于 API 动态参数 |
| 订单详情接口 | `auto_delivery_handler.py` 中 `_fetch_order_detail_from_api` | 已抽到 `services/delivery/orders.py` 并通过 `XianyuApis` 暴露解析和过期判断 helper |
| 发货日志 | `auto_delivery_handler.py` 的 `_record_delivery_log` 思路 | 已落地为 `delivery_logs` 基础表，不接入后台消息日志表 |
| 禁止重复发货 | `can_auto_delivery`、`mark_delivery_sent`、锁相关逻辑 | 已用 `delivery_logs` 的订单发送记录实现幂等跳过 |
| `data` 库存消费 | `auto_delivery_handler.py` 中 `consume_batch_data` 的业务意图 | 已用 SQLite 事务按订单数量预占库存行，发送成功标记 `sent`，失败保留为 `failed_retryable` 并支持同订单重试复用 |

暂不迁入：多级代理卡券、亦凡 API、免拼、自动确认发货、买家信用拦截、Redis 锁、后台通知。

## 重新上架

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 商品同步和归属校验 | `xianyu-auto-reply/common/services/item_service.py` | 已参考 `fetch_all_items_from_account`、`get_item` 和 `update_item` 思路；MVP 读取本地 SQLite `items` 商品快照确认归属，不迁入 SQLAlchemy/Redis |
| 商品操作 API 调用模式 | `xianyu-auto-reply/promotion/backend/app/services/item_delete_api_service.py` | 已参考 mtop seller API 的签名、Cookie、Set-Cookie 合并和 token 过期重试模式，落地为可注入 API 结果边界；未硬编码未知重新上架接口，也不复用删除动作本身 |
| Playwright 兜底浏览器控制 | `xianyu-auto-reply/common/services/promotion_xianyu_publisher.py`、`backend-web/app/services/xianyu_publisher.py` | 已落地 Cookie 域、商品管理 URL 和安全 fallback 命令描述；默认不启动浏览器，不走空白发布表单、图片上传和新建商品流程 |
| 商品管理数量/状态判断 | `promotion/backend/app/services/publish_rule_scheduler.py`、`common/services/item_service.py` | 已基于商品快照状态、标题和 `item_id` 回查做 `already_active`、标题不匹配和归属失败判断 |
| 上架后绑定发货内容 | `promotion/backend/app/services/publish_coupon_card_service.py` | 已改为 upsert 本地 `delivery_configs`，重新上架成功或已处于上架状态后绑定目标 `item_id` |

MVP 重新上架的目标是“对一个已经发布过、仍能在商品管理中找到的商品执行重新上架”。当前实现先完成本地任务记录、归属校验、已上架幂等跳过、API 结果解析边界、Playwright fallback 命令构造和发货配置绑定。如果后续抓到稳定的闲鱼重新上架 mtop API，优先把真实调用接入现有可注入 API 边界；如果接口不可用，再在用户授权后用 Playwright 打开商品管理页定位目标商品并点击“重新上架”。无论哪条路径，都必须记录前置状态、动作结果、最终商品状态和截图或响应摘要。

暂不迁入：素材库后台、发布规则定时器、返佣选品、从本地草稿创建全新商品、发布删除规则、用户权限和管理页面。

## 后续实现约束

1. 每新增一个功能，先在本文件补充参考来源。
2. 迁移代码时保留关键协议字段、错误判断和日志语义。
3. 删除或替换重项目依赖时，要在 PR 描述中说明替换方式。
4. 如果参考项目中已有测试，优先迁移测试意图；没有测试时补最小单元测试。
5. 文档、README 和实际 CLI 命令必须同步更新。
