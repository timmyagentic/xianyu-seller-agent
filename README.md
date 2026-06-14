# xianyu-seller-agent

轻量级闲鱼卖家自动化 Agent。项目目标不是再做一个完整管理后台，而是在现有自动回复能力上，补齐卖家最常用的三个闭环：

1. 自动回复
2. 自动发货
3. 自动上架商品

当前代码已经具备自动回复的基础能力：扫码登录或 Cookie 登录、闲鱼 WebSocket 长连接、消息解密、商品信息读取、SQLite 对话上下文、LLM 意图路由和人工接管。接下来的开发重点是把自动发货和自动上架做成同一个 Python 项目内的轻量模块。

## MVP 定位

`xianyu-seller-agent` 面向单账号或少量账号的本地托管场景，优先保证部署简单、链路清楚、失败可追踪。

不做重后台，不做多租户 SaaS，不做复杂分销、返佣、财务、权限和前端管理系统。需要配置的内容先通过本地文件和 SQLite 管理；需要人工介入的风险控制保留人工确认入口。

## 当前状态

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 闲鱼登录 | 已有 | 支持 `.env` Cookie，也支持 `python main.py --qr-login` 扫码写入 Cookie |
| 消息监听 | 已有 | 通过闲鱼 WebSocket 接收聊天消息，维护心跳和 token 刷新 |
| 自动回复 | 已有 | 按价格、技术、默认场景路由到不同 prompt，支持上下文 |
| 人工接管 | 已有 | 卖家发送切换关键词，默认 `。`，暂停或恢复某个会话自动回复 |
| 自动发货 | 待实现 | 计划基于订单事件、商品绑定的发货内容和 IM 发送完成 |
| 自动上架 | 待实现 | 计划基于 Playwright 控制闲鱼发布页完成单品发布 |

## 目标架构

```text
xianyu-seller-agent/
├── main.py                    # 进程入口，负责登录、启动消息监听和任务循环
├── XianyuApis.py              # 闲鱼 H5 API：token、商品信息，后续扩展订单接口
├── XianyuAgent.py             # LLM 自动回复与意图路由
├── context_manager.py         # SQLite 持久化入口
├── xianyu_qr_login.py         # 扫码登录
├── services/
│   ├── delivery/              # 自动发货：订单识别、发货内容、发送、日志
│   └── listing/               # 自动上架：商品草稿、图片处理、发布器
├── docs/
│   └── superpowers/specs/     # MVP 设计文档
└── prompts/                   # 回复 prompt 模板
```

设计文档见 [MVP 设计](docs/superpowers/specs/2026-06-14-xianyu-seller-agent-mvp-design.md)。

## 功能设计摘要

### 自动回复

自动回复继续复用现有实现。收到买家消息后，系统会读取商品信息和会话历史，先通过规则识别价格/技术类问题，再用 LLM 分类兜底。回复发送前会过滤明显的平台外交易词，卖家也可以通过人工接管关键词暂停某个会话的自动回复。

### 自动发货

MVP 只做虚拟商品发货。每个商品可以绑定一条或多条发货内容，内容类型先支持：

- `text`：固定文本，例如网盘链接、兑换说明
- `data`：一次性库存文本，例如卡密，一单消费一行
- `api`：调用外部接口取货，失败可重试

触发条件以闲鱼订单消息或待发货订单轮询为准。系统拿到订单号、买家、商品 ID 和规格后，匹配商品发货配置，生成发货内容，通过当前 WebSocket 会话发送给买家，并记录状态。发货成功后再考虑调用闲鱼确认发货接口；MVP 先把“发货内容已成功发送给买家”作为第一阶段成功标准。

### 自动上架

MVP 只做单品发布。商品草稿包含标题、描述、价格、库存、图片和发货配置。发布器使用 Playwright 打开闲鱼发布页，注入 Cookie，上传图片，填写描述、价格、地址和包邮选项，点击发布并记录结果。

自动上架不在第一版做批量调度和素材库后台；先提供本地 JSON/YAML 草稿和命令行发布能力，验证成功后再扩展批量发布。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

配置 `.env`：

```env
API_KEY=your_model_api_key
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max
COOKIES_STR=your_goofish_cookie
TOGGLE_KEYWORDS=。
SIMULATE_HUMAN_TYPING=False
```

首次登录或 Cookie 失效时：

```bash
python main.py --qr-login
```

启动自动回复：

```bash
python main.py
```

## 开发原则

- 先保留单进程 Python 架构，避免引入 FastAPI、React、MySQL、Redis 等重依赖。
- 自动发货和自动上架都必须有幂等记录，避免重复发货或重复发布。
- 所有高风险动作都要可关闭、可重试、可审计。
- 平台风控、滑块验证、Cookie 失效时不强行绕过，记录原因并要求人工处理。
- 默认只面向学习、研究和个人本地使用，使用者需要自行遵守平台规则。

## 参考来源

本项目基于 `XianyuAutoAgent` 的自动回复链路继续演进；自动发货和商品发布会参考本机另一个重项目 `xianyu-auto-reply` 的业务拆分，但不会照搬其多服务后台架构。
