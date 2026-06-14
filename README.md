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

当前仓库已迁入 `XianyuAutoAgent` 的自动回复基线代码，并补充了本地 Python 脚手架、共享消息解析层、SQLite 发货配置 CLI 和幂等虚拟发货服务。付款消息接入、API 发货和重新上架仍在后续阶段实现。现有文档和项目文件用于约束后续实现边界：

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

代码迁入后使用标准 Python 本地运行方式：

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

后续 CLI 应保持 `python main.py` 等价于启动自动回复，同时扩展：

```bash
python main.py delivery add --item-id 123 --type text --content "..."
python main.py delivery list --item-id 123
python main.py listing relist --item-id 123
python main.py listing relist relist/item-001.json
python main.py listing status
```

## 开发原则

- 先迁移自动回复，再扩展自动发货和重新上架。
- 实现前必须先定位两个参考项目中的既有实现，禁止凭空重写。
- 从 `xianyu-auto-reply` 迁移时只保留业务算法和协议细节，替换掉重后台依赖。
- SQLite 是 MVP 唯一持久化存储。
- 所有发货和重新上架动作必须可关闭、可重试、可审计、可幂等。
- `data` 类型发货必须先在 SQLite 事务中按订单数量预占对应库存行，不能在发送成功后才消费库存。
- 风控、滑块验证、Cookie 失效时停止自动动作，记录原因并交给人工处理。
