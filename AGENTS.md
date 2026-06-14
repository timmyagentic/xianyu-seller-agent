# Repository Guidelines

## 项目结构与模块组织

本仓库当前是文档先行项目，根目录包含 `README.md`，设计文档在 `docs/superpowers/specs/`，参考实现映射在 `docs/reference-implementation-map.md`。后续代码应先迁入 `XianyuAutoAgent` 的根级 Python 结构：`main.py`、`XianyuApis.py`、`XianyuAgent.py`、`context_manager.py`、`xianyu_qr_login.py` 和 `prompts/`。新增能力放入 `services/messages/`、`services/delivery/`、`services/listing/`。运行时数据放 `data/`，重新上架任务配置放 `relist/`，这些本地数据默认不提交。

## 构建、测试与开发命令

当前仓库尚无可运行代码。代码迁入后使用：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --qr-login
python main.py
```

`python main.py --qr-login` 用于刷新 Cookie，`python main.py` 启动自动回复。后续 CLI 应兼容 `python main.py delivery add ...`、`python main.py listing relist --item-id 123` 和 `python main.py listing relist relist/item-001.json`。

## 编码风格与命名

使用 Python 3、4 空格缩进、显式导入和小模块。函数、变量、文件和 CLI 参数使用 `snake_case`，类名使用 `PascalCase`。不要引入 FastAPI、React、MySQL 或 Redis，除非 MVP 范围被明确修改。从 `xianyu-auto-reply` 迁移时只保留业务算法和协议细节，替换重后台依赖。

## 测试规范

代码迁入后使用 `pytest`，测试放在 `tests/`，文件命名为 `test_*.py`。优先覆盖消息解析、人工接管、意图路由、安全过滤、订单幂等、库存预占事务、多数量库存预占、API 发货失败、重新上架配置校验、商品归属校验和重新上架结果解析。Playwright 真实重新上架属于人工验收；单元测试只覆盖字段映射、状态解析和错误分支。

## 提交与 PR 规范

历史提交使用 Conventional Commit，例如 `docs: initialize xianyu seller agent`。继续使用 `docs:`、`feat:`、`fix:`、`test:`、`refactor:`。PR 必须说明参考了哪个源项目文件、做了哪些裁剪、运行了哪些验证，以及是否涉及 `.env`、Cookie、发货或发布风险。

## 安全与配置

禁止提交 `.env`、Cookie、API Key、SQLite 运行库、买家信息和发货库存。自动发货、自动确认和自动重新上架默认关闭。遇到风控、滑块验证或 Cookie 失效时，记录原因并要求人工处理，不要实现绕过逻辑。
