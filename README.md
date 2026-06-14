# xianyu-seller-agent

`xianyu-seller-agent` 是一个轻量级闲鱼卖家自动化项目。它不是重新发明一套系统，而是把两个已有项目中的能力重新整合成一个单进程、低依赖、易部署的 Python 工具。

## 项目定位

当前项目首先要完整承接 `XianyuAutoAgent` 的自动回复能力。也就是说，第一阶段的事实目标不是自动发货或自动重新上架，而是把现有自动回复链路稳定迁入本仓库：

- Cookie 或扫码登录
- 闲鱼 WebSocket 长连接、注册、ACK、心跳和 token 刷新
- 消息解密、消息过滤、聊天消息解析
- 商品信息读取和 SQLite 缓存
- 对话上下文、议价次数、人工接管
- LLM 意图路由和安全过滤
- 通过 IM 会话发送自动回复

在这个基础上，再从 `xianyu-auto-reply` 中抽取自动发货、订单解析、商品管理、重新上架和上架后绑定发货内容等局部实现。`xianyu-auto-reply` 是参考实现，不是目标架构；本项目不会照搬它的 React 后台、MySQL、Redis、多服务部署、返佣体系和复杂权限模型。

## 当前仓库状态

当前仓库已迁入 `XianyuAutoAgent` 的自动回复基线代码，并补充了本地 Python 脚手架、共享消息解析层、SQLite 发货配置 CLI、幂等虚拟发货服务、API 发货客户端、订单详情解析、重新上架任务记录、商品归属校验和上架后发货配置绑定。真实付款消息和真实重新上架点击仍需要账号授权后的人工验收。现有文档和项目文件用于约束后续实现边界：

- [MVP 设计](docs/superpowers/specs/2026-06-14-xianyu-seller-agent-mvp-design.md)
- [参考实现映射](docs/reference-implementation-map.md)
- [贡献指南](AGENTS.md)
- [实施计划](docs/superpowers/plans/2026-06-14-xianyu-seller-agent-mvp.md)

## 参考项目职责

| 来源项目 | 使用方式 | 重点参考 |
| --- | --- | --- |
| `XianyuAutoAgent` | 自动回复基线，优先完整迁入 | `main.py`、`XianyuApis.py`、`XianyuAgent.py`、`context_manager.py`、`xianyu_qr_login.py`、`prompts/` |
| `xianyu-auto-reply` | 功能仓库，只抽局部实现 | `MessageHandler`、`AutoDeliveryHandler`、`delivery_utils`、商品同步、商品操作 API、发布器 Cookie/浏览器经验、发布后建卡逻辑 |

## MVP 范围

MVP 保留单账号或少量账号的本地托管形态，目标是完成三个闭环：

1. 买家咨询时自动回复。
2. 买家付款后自动发送虚拟商品内容。
3. 卖家指定一个已经发布过的商品，执行重新上架，并把重新上架后的商品绑定到发货配置。

明确不做：多租户 SaaS、Web 管理后台、返佣分销、复杂权限、MySQL、Redis、批量采集、从本地草稿创建全新商品、自动绕过风控或滑块验证。

## 目标目录结构

```text
xianyu-seller-agent/
├── main.py                    # CLI 入口，启动登录、监听和任务循环
├── XianyuApis.py              # 闲鱼 H5 API：token、商品、订单
├── XianyuAgent.py             # 自动回复、意图路由和 prompt 加载
├── context_manager.py         # SQLite 持久化和迁移入口
├── xianyu_qr_login.py         # 扫码登录
├── services/
│   ├── messages/              # 消息解析、去重、分发
│   ├── delivery/              # 自动发货配置、触发、发送、日志
│   └── listing/               # 已有商品重新上架、商品状态校验、发货绑定
├── prompts/                   # 回复 prompt 模板
├── data/                      # 本地 SQLite 和运行时文件，禁止提交
├── relist/                    # 本地重新上架任务配置示例
└── docs/                      # 设计和参考映射
```

## 预期开发命令

使用标准 Python 本地运行方式：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
cp .env.example .env
python main.py --qr-login
python main.py
```

在尚未创建虚拟环境时，也可以用 `uv run --with pytest python -m pytest -q` 临时运行测试；真实运行仍应使用 `.venv` 和 `requirements.txt`。

`python main.py` 等价于启动自动回复；帮助和本地配置命令不会要求 Cookie：

```bash
python main.py --help
python main.py delivery --help
python main.py listing --help
```

自动发货配置 CLI：

```bash
python main.py delivery add --item-id 123 --type text --content "固定发货内容"
python main.py delivery add --item-id 456 --type data --name "一次性卡密"
python main.py delivery inventory add --config-id 2 --content-file relist/local-keys.txt
python main.py delivery list --item-id 123
python main.py delivery inventory list --config-id 2
```

`text` 类型适合同一商品所有买家收到相同内容；`data` 类型适合卡密、兑换码、账号 key 等一次性库存。`delivery inventory list` 默认只显示库存状态，不显示正文；确需本地排查时再加 `--show-content`。`relist/local-keys.txt` 这类库存文件只应放本地，不要提交。

重新上架任务 CLI：

```bash
python main.py listing fetch-items
python main.py listing relist --item-id 123
python main.py listing relist --item-id 123 --stock 7
python main.py listing auto-relist set --item-id 123 --stock 7
python main.py listing auto-relist list --item-id 123
python main.py listing relist relist/item-001.json
python main.py listing status
```

`listing fetch-items` 会参考 `xianyu-auto-reply` 的商品同步策略，调用闲鱼 `mtop.idle.web.xyh.item.list` 在售分组接口，分页获取当前账号所有已发布商品并写入本地 `items` 快照表。

`listing relist` 默认不会执行真实平台点击；它先检查本地商品快照，已上架时幂等记录 `already_active` 并刷新发货绑定，未上架且没有授权 API/浏览器执行器时记录 `manual_required` 或 `playwright_required`。`--stock` 会作为目标库存写入重上架任务，并在后续接入真实 API 或授权浏览器执行器时传递给执行边界。

`listing auto-relist set` 用于配置“发货成功后自动重新上架”的商品级策略。运行时还必须开启 `AUTO_RELIST_ENABLED=true`；否则配置只会保存，不会在付款发货后触发。

## 配置与默认关闭项

复制 `.env.example` 为 `.env` 后再填入真实配置。`.env`、Cookie、SQLite 运行库、买家信息、发货库存和真实重新上架任务都不应提交。

关键开关：

- `MODEL_BASE_URL=https://api-inference.modelscope.cn/v1` 与 `MODEL_NAME=deepseek-ai/DeepSeek-V4-Pro`：默认使用 ModelScope 的 OpenAI 兼容接口；真实 `API_KEY` 只写入本地 `.env`。
- `LLM_ENABLE_SEARCH=false`：默认不发送供应商特定的联网搜索扩展参数。
- `COOKIE_REFRESH_ENABLED=true`：默认每 10 分钟调用登录态续期接口合并 Set-Cookie，减少 `_m_h5_tk` 令牌过期导致的掉线；Session 过期、滑块或风控仍需人工重新登录。
- `AUTO_REPLY_ENABLED=true`：控制普通买家聊天是否进入 LLM 自动回复；付款完成消息仍由 `AUTO_DELIVERY_ENABLED` 单独控制。
- `AUTO_DELIVERY_ENABLED=false`：自动发货默认关闭。确认商品发货配置、库存和测试订单后，才在本地 `.env` 改成 `true`。
- `AUTO_CONFIRM_DELIVERY_ENABLED=false`：自动确认发货默认关闭。
- `AUTO_RELIST_ENABLED=false`：发货后自动重新上架默认关闭；即使商品已配置 `listing auto-relist set`，未打开该开关也不会触发。
- `AUTO_RELIST_ALLOW_PLAYWRIGHT=false`：默认不允许自动创建浏览器执行任务；遇到没有稳定 API 的真实重新上架时只记录 `manual_required`。

启用自动发货后，程序会监听“我已付款，等待你发货”“等待卖家发货”等付款完成消息，解析订单号、商品 ID、买家和会话，再按商品配置发货。同一订单已经写入 `sent` 日志后会跳过；`data` 库存会按订单购买数量先预占，发送成功后标记 `sent`，发送失败时保留为 `failed_retryable` 以便同一订单重试继续使用原 key。发货成功后，如果同时开启 `AUTO_RELIST_ENABLED=true` 且该商品存在启用的 `auto-relist` 配置，程序会创建重新上架任务并记录目标库存；失败只影响重新上架任务日志，不回滚已发货结果。

遇到 Cookie 失效、滑块、风控、账号归属不清或真实交易风险时，程序应记录原因并交给人工处理，不实现绕过逻辑。

## 测试与人工验收

默认验证只使用单元测试、fake/mocks 和 CLI 帮助命令，不需要真实闲鱼账号：

```bash
python -m py_compile main.py XianyuApis.py XianyuAgent.py context_manager.py xianyu_qr_login.py utils/xianyu_utils.py services/messages/*.py services/delivery/*.py services/listing/*.py
python -m pytest -q
python main.py --help
python main.py delivery --help
python main.py delivery inventory --help
python main.py listing --help
```

人工验收需要用户明确提供账号授权后再做：

1. `python main.py --qr-login` 刷新 Cookie。
2. `python main.py` 启动自动回复并验证一条买家咨询。
3. 使用测试订单或用户确认的真实订单验证一次幂等发货。
4. 对用户确认的已发布商品执行重新上架或确认 `already_active` 跳过，并检查 `listing_jobs` 记录。

## 开发原则

- 先迁移自动回复，再扩展自动发货和重新上架。
- 实现前必须先定位两个参考项目中的既有实现，禁止凭空重写。
- 从 `xianyu-auto-reply` 迁移时只保留业务算法和协议细节，替换掉重后台依赖。
- SQLite 是 MVP 唯一持久化存储。
- 所有发货和重新上架动作必须可关闭、可重试、可审计、可幂等。
- `data` 类型发货必须先在 SQLite 事务中按订单数量预占对应库存行，不能在发送成功后才消费库存。
- 风控、滑块验证、Cookie 失效时停止自动动作，记录原因并交给人工处理。
