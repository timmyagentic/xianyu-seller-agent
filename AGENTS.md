# Repository Guidelines

## 项目结构与模块组织

本仓库是单进程 Python 项目，根级自动回复结构来自 `XianyuAutoAgent`：`main.py`、`XianyuApis.py`、`XianyuAgent.py`、`context_manager.py`、`xianyu_qr_login.py`、`utils/` 和 `prompts/`。新增能力放入 `services/messages/`、`services/delivery/`、`services/listing/`。设计文档在 `docs/superpowers/specs/`，实施计划在 `docs/superpowers/plans/`，参考实现映射在 `docs/reference-implementation-map.md`。运行时数据放 `data/`，重新上架任务配置放 `relist/`，这些本地数据默认不提交。

## 构建、测试与开发命令

本地开发使用：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python main.py --qr-login
python main.py
```

`python main.py --qr-login` 用于刷新 Cookie，`python main.py` 启动自动回复。CLI 兼容 `python main.py delivery add ...`、`python main.py delivery list ...`、`python main.py listing relist --item-id 123`、`python main.py listing relist relist/item-001.json` 和 `python main.py listing status`。无真实 Cookie 时只运行测试和帮助命令，不启动真实平台动作。

## 编码风格与命名

使用 Python 3、4 空格缩进、显式导入和小模块。函数、变量、文件和 CLI 参数使用 `snake_case`，类名使用 `PascalCase`。不要引入 FastAPI、React、MySQL 或 Redis，除非 MVP 范围被明确修改。从 `xianyu-auto-reply` 迁移时只保留业务算法和协议细节，替换重后台依赖。

## 测试规范

代码迁入后使用 `pytest`，测试放在 `tests/`，文件命名为 `test_*.py`。优先覆盖消息解析、人工接管、意图路由、安全过滤、订单幂等、库存预占事务、多数量库存预占、API 发货失败、重新上架配置校验、商品归属校验和重新上架结果解析。Playwright 真实重新上架属于人工验收；单元测试只覆盖字段映射、状态解析和错误分支。

## 提交与 PR 规范

历史提交使用 Conventional Commit，例如 `docs: initialize xianyu seller agent`。继续使用 `docs:`、`feat:`、`fix:`、`test:`、`refactor:`。PR 必须说明参考了哪个源项目文件、做了哪些裁剪、运行了哪些验证，以及是否涉及 `.env`、Cookie、发货或发布风险。

每个需求都必须从最新 `origin/main` 新开独立 git worktree 和 `codex/` 前缀分支执行，不要直接在主工作区或 `main` 上改需求。推荐 worktree 位置为 `/Volumes/SamsungDisk/Code/.worktrees/xianyu-seller-agent-<short-slug>`。完成后必须 push 分支并新建 PR；PR 合并后再快进本地主工作区并清理对应 worktree、本地分支和远端分支。

## 安全与配置

禁止提交 `.env`、Cookie、API Key、SQLite 运行库、买家信息和发货库存。自动发货、自动确认和自动重新上架默认关闭。遇到风控、滑块验证或 Cookie 失效时，记录原因并要求人工处理，不要实现绕过逻辑。

项目私有 `.env` 只放主 checkout 根目录，例如 `/Volumes/SamsungDisk/Code/xianyu-seller-agent/.env`，不要放全局上层目录，也不要放临时 worktree。临时 worktree 只用于开发、测试和 PR，不作为长期 live/web 服务运行目录；删除 worktree 前必须确认没有 `python main.py`、`python main.py web`、`screen` 会话或打开的 SQLite/日志仍指向该 worktree。长期运行统一从主 checkout 使用 `scripts/xianyu-service.sh`，必要时先跑 `scripts/xianyu-service.sh doctor` 检查进程 cwd 和端口占用。

## 账号与平台约束

当前绑定的闲鱼账号已经开通鱼小铺。发布、重新发布和多库存相关能力必须同时考虑普通闲鱼发布页和 seller 工作台：无库存要求的重新发布可使用 `https://www.goofish.com/publish?itemId=...&editScene=rePutOn`；涉及平台侧库存、鱼小铺商品管理和多库存验证时，优先使用 `https://seller.goofish.com/?site=COMMONPRO#/seller-item/goods-manage` 或 `#/seller-item/publish`。

目标库存存在时，Playwright 执行器必须真实找到并填写库存输入框，找不到库存输入框时返回结构化失败，不要继续点击发布或伪造平台侧库存修改成功。旧的 `#/seller-item` 路由不是当前可用的商品管理页；不要把它作为默认 seller 路由。
