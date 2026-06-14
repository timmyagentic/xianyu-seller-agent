# 参考实现映射

本项目的功能都应从已有项目迁移或改写，不应凭空实现。实现前先查本文件，确认应参考的源文件和需要裁剪的部分。

## 来源项目定位

| 项目 | 本项目中的角色 | 使用规则 |
| --- | --- | --- |
| `/Volumes/SamsungDisk/Code/XianyuAutoAgent` | 自动回复主基线 | 优先完整迁入，保持行为一致，再做小幅结构整理 |
| `/Volumes/SamsungDisk/Code/xianyu-auto-reply` | 自动发货、自动上架、订单和发布参考库 | 只抽业务实现和协议细节，避免带入重后台架构 |

## 自动回复

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 进程入口、WebSocket、ACK、心跳、token 刷新 | `XianyuAutoAgent/main.py` | 作为第一阶段主骨架；修正全局 `bot` 依赖，改为注入 |
| 消息解密和基础过滤 | `XianyuAutoAgent/main.py` | 保留 base64/加密双路径、过期消息过滤和系统消息过滤 |
| 商品信息 API | `XianyuAutoAgent/XianyuApis.py` | 保留 token、登录状态检查、商品详情获取；后续扩展订单接口 |
| LLM 自动回复和意图路由 | `XianyuAutoAgent/XianyuAgent.py` | 保留 `price`、`tech`、`default`、`no_reply` 路由和安全过滤 |
| SQLite 上下文 | `XianyuAutoAgent/context_manager.py` | 保留 `messages`、`chat_bargain_counts`、`items`，新增迁移表 |
| 扫码登录 | `XianyuAutoAgent/xianyu_qr_login.py` | 直接迁入并保持 `python main.py --qr-login` |
| prompt 模板 | `XianyuAutoAgent/prompts/` | 迁入为默认模板，允许用户覆盖非 `_example` 文件 |

## 消息解析增强

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 消息去重和分发 | `xianyu-auto-reply/websocket/app/services/xianyu/message_handler.py` | 改写为轻量 `services/messages/`，不要依赖数据库配置和后台回调 |
| 卡片更新消息 | 同上 | 用于付款状态变更和订单触发，保留解析逻辑 |
| 营销/系统提示过滤 | 同上 | 保留明确的 `MsgTips` 过滤判断，避免误杀交易消息 |

## 自动发货

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| 发货触发、订单幂等、发送重试 | `xianyu-auto-reply/websocket/app/services/xianyu/auto_delivery_handler.py` | 改写为 SQLite + 本地锁；不迁入 Redis 分布式锁 |
| 内容变量替换 | `xianyu-auto-reply/websocket/app/services/xianyu/delivery_utils.py` | 保留 `{order_id}`、`{item_id}`、`{buyer_id}` 等变量 |
| 订单详情接口 | `auto_delivery_handler.py` 中 `_fetch_order_detail_from_api` | 抽到 `XianyuApis.py` 或 `services/delivery/orders.py` |
| 发货日志 | `auto_delivery_handler.py` 的 `_record_delivery_log` 思路 | 落地为 `delivery_logs`，不接入后台消息日志表 |
| 禁止重复发货 | `can_auto_delivery`、`mark_delivery_sent`、锁相关逻辑 | 第一版用订单号唯一约束和进程内锁即可 |

暂不迁入：多级代理卡券、亦凡 API、免拼、自动确认发货、买家信用拦截、Redis 锁、后台通知。

## 自动上架

| 能力 | 参考文件 | 迁移说明 |
| --- | --- | --- |
| Playwright 发布器 | `xianyu-auto-reply/backend-web/app/services/xianyu_publisher.py` | 抽出图片上传、表单填写、价格、包邮、地址、发布按钮流程 |
| 卖家发布页适配 | `xianyu-auto-reply/common/services/promotion_xianyu_publisher.py` | 参考 `seller.goofish.com` 发布入口和库存填写 |
| 发布执行编排 | `xianyu-auto-reply/common/services/promotion_publish_execution_service.py` | 改写为本地 CLI：校验账号、解析草稿、调用发布器、记录结果 |
| 发布追踪码 | `promotion/backend/app/services/publish_rule_scheduler.py` | 保留标题追踪码思路，用于发布后回查商品 ID |
| 发布后绑定发货内容 | `promotion/backend/app/services/publish_coupon_card_service.py` | 不创建后台卡券，改为写入或更新本地 `delivery_configs` |
| 图片路径处理 | `xianyu_publisher.py` 的 `_resolve_upload_image_path` | 支持本地路径和远程图片下载，临时文件要清理 |

暂不迁入：素材库后台、发布规则定时器、返佣选品、发布删除规则、用户权限和管理页面。

## 后续实现约束

1. 每新增一个功能，先在本文件补充参考来源。
2. 迁移代码时保留关键协议字段、错误判断和日志语义。
3. 删除或替换重项目依赖时，要在 PR 描述中说明替换方式。
4. 如果参考项目中已有测试，优先迁移测试意图；没有测试时补最小单元测试。
5. 文档、README 和实际 CLI 命令必须同步更新。
