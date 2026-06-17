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

当前仓库已迁入 `XianyuAutoAgent` 的自动回复基线代码，并补充了本地 Python 脚手架、共享消息解析层、SQLite 发货配置 CLI、幂等虚拟发货服务、API 发货客户端、订单详情解析、重新上架任务记录、真实商品状态刷新、商品归属校验、授权 Playwright 重新上架执行器和上架后发货配置绑定。真实付款消息和真实重新上架仍需要账号授权后的人工验收；遇到登录失效、滑块、验证码或风控时只记录结构化失败，不做绕过。现有文档和项目文件用于约束后续实现边界：

- [MVP 设计](docs/superpowers/specs/2026-06-14-xianyu-seller-agent-mvp-design.md)
- [参考实现映射](docs/reference-implementation-map.md)
- [贡献指南](AGENTS.md)
- [实施计划](docs/superpowers/plans/2026-06-14-xianyu-seller-agent-mvp.md)

## 账号与平台约束

当前项目绑定的闲鱼账号已经开通鱼小铺。涉及平台侧多库存、商品管理库存列、鱼小铺发布能力时，应优先使用 `https://seller.goofish.com` 卖家工作台路径验证；普通重新发布仍可使用 `https://www.goofish.com/publish?itemId=...&editScene=rePutOn` 作为 fallback，但这个普通页面没有库存输入框时，不能继续点击发布并声称库存已同步。

真实验证结果显示，鱼小铺商品管理入口是 `https://seller.goofish.com/?site=COMMONPRO#/seller-item/goods-manage`，可以看到商品 `1030573156061 / 智谱 GLM coding plan`、库存列和当前库存值；旧的 `#/seller-item` 会落到无效微应用，不应再作为默认商品管理路由。鱼小铺发布入口可配置为 `https://seller.goofish.com/?site=COMMONPRO#/seller-item/publish`，参考项目中该页面包含库存输入策略。后续如果更换为未开通鱼小铺的账号，再回退到普通账号路径。

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

## 稳定服务启动

本项目有两个常驻服务面：

- `live`：`python main.py`，负责闲鱼 WebSocket、自动回复、付款消息自动发货、确认发货和发货后重新上架 hook。
- `web`：`python main.py web`，负责本地管理页面和本地 API。

不要再手动进入某个临时 worktree 后用 `screen` 拼命令启动。仓库提供统一脚本，脚本会从自身位置解析稳定项目根目录，自动使用该根目录下的 `.venv`、`.env`、`data/` 和 `logs/`：

```bash
./scripts/xianyu-service.sh setup
./scripts/xianyu-service.sh qr-login
./scripts/xianyu-service.sh start
./scripts/xianyu-service.sh status
./scripts/xianyu-service.sh logs
./scripts/xianyu-service.sh restart
./scripts/xianyu-service.sh stop
```

常用流程：

1. 在主仓库 `/Volumes/SamsungDisk/Code/xianyu-seller-agent` 执行 `./scripts/xianyu-service.sh setup` 创建或修复 `.venv`。
2. 如果 `.env` 里没有有效 `COOKIES_STR`，执行 `./scripts/xianyu-service.sh qr-login` 扫码登录。
3. 执行 `./scripts/xianyu-service.sh start` 同时启动 live 和 web。
4. 执行 `./scripts/xianyu-service.sh status` 查看两个 `screen` 会话是否在跑。
5. 执行 `./scripts/xianyu-service.sh logs` 查看 `logs/live.log` 和 `logs/web.log`。

如果之前已经从 worktree 手动启动过 `xianyu-seller-agent-live` 或 `xianyu-seller-agent-web`，先在主仓库执行：

```bash
./scripts/xianyu-service.sh restart
```

`restart` 会停止同名旧 `screen` 会话，再从当前脚本所在的稳定项目根目录重新启动，避免运行目录继续依赖 `/Volumes/SamsungDisk/Code/.worktrees/...`。

可选覆盖项：

```bash
XIANYU_AGENT_ROOT=/Volumes/SamsungDisk/Code/xianyu-seller-agent ./scripts/xianyu-service.sh start
XIANYU_AGENT_LOG_DIR=/tmp/xianyu-logs ./scripts/xianyu-service.sh logs
XIANYU_WEB_LOG_LEVEL=DEBUG ./scripts/xianyu-service.sh restart
LINES=200 ./scripts/xianyu-service.sh logs
```

`python main.py` 等价于启动自动回复；帮助和本地配置命令不会要求 Cookie：

```bash
python main.py --help
python main.py web --host 127.0.0.1 --port 8765
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
python main.py listing item-status --item-id 123
python main.py listing relist-preflight --item-id 123 --expected-title "商品标题" --stock 7
python main.py listing relist --item-id 123
python main.py listing relist --item-id 123 --stock 7
python main.py listing relist --item-id 123 --stock 7 --allow-playwright --confirm-real-relist
python main.py listing publish --title "商品标题" --description "商品描述" --price 9.90 --stock 7 --image /path/to/image.png --confirm-real-publish
python main.py listing auto-relist set --item-id 123 --stock 7
python main.py listing auto-relist list --item-id 123
python main.py listing relist relist/item-001.json
python main.py listing status
```

`listing fetch-items` 会参考 `xianyu-auto-reply` 的商品同步策略，调用闲鱼 `mtop.idle.web.xyh.item.list` 在售分组接口，分页获取当前账号所有已发布商品并写入本地 `items` 快照表。

`listing item-status` 会只读刷新单个商品的真实平台状态，并把脱敏后的状态摘要输出到终端，同时更新本地 `items` 快照。它会区分 `active`、`inactive`、`sold`、`relistable` 等状态，并保留平台原始状态码、状态文案、状态来源和 `can_relist` 判断，便于在执行重新上架前确认当前商品是不是旧快照误判。

`listing relist-preflight` 会在不点击、不填库存、不写 `listing_jobs` 的前提下打开授权浏览器做页面预检：先刷新单商品真实状态，再进入普通发布页的重新发布路由 `https://www.goofish.com/publish?itemId=...&editScene=rePutOn`，检查页面是否能看到目标商品和发布入口。它用于真实执行前收集页面证据；遇到登录、滑块、验证码、风控、找不到商品或找不到按钮时只返回结构化失败。为便于排查页面不可执行原因，preflight 会输出安全的 `page_evidence`，包括当前 URL、页面标题、正文长度、命中的状态标记和 input/button 数量，但不会输出完整页面正文。

`listing relist` 会在 `COOKIES_STR` 存在时先通过当前账号刷新商品真实状态：优先查询在售列表，未命中时再用商品详情接口兜底，避免本地旧快照把下架/售出商品误判为 `already_active`。如果配置了 `XIANYU_RELIST_API`，会按 `xianyu-auto-reply` 的 seller mtop 操作模式签名调用该接口；未配置或 API 失败时，默认记录 `manual_required`。只传 `--allow-playwright` 时不会点击页面，只会在任务中记录需要授权浏览器执行；只有同时传入 `--allow-playwright --confirm-real-relist`，CLI 才会创建真实 Playwright 执行器。

授权 Playwright 执行器只处理“普通重新发布页已打开目标商品并出现发布入口”的场景：它会尝试设置目标库存、点击“发布/立即发布”，并且只有页面出现“操作成功/发布成功/上架成功/已上架/在售”等确认文本后才记录 `relisted`。普通闲鱼账号的重新发布页可能没有库存输入框；这种情况下 `--stock` 会保留在本地任务和 API 边界里，但不会伪造平台库存修改成功。如果检测到登录页、滑块、验证码、风控提示、找不到目标商品、找不到按钮或点击后没有确认结果，会记录 `playwright_required` 和失败原因，必要时保存截图到 `AUTO_RELIST_SCREENSHOT_DIR`。`--stock` 会作为目标库存写入任务，并传递给 mtop API 或授权浏览器执行器。mtop API 或 Playwright 确认成功后，服务会再尝试刷新一次单商品真实状态，把执行后状态写入本地快照、`listing_jobs.final_status`、响应摘要和 `listing_jobs.evidence_json`；如果刷新失败，则保留平台动作确认结果。`evidence_json` 会脱敏记录请求摘要、执行前状态、动作来源、Playwright 页面证据和执行后状态，便于 `listing status` 审计。

`listing auto-relist set` 用于配置“发货成功后自动重新上架”的商品级策略。运行时还必须开启 `AUTO_RELIST_ENABLED=true`；否则配置只会保存，不会在付款发货后触发。

Playwright 路径会参考 `xianyu-auto-reply` 的页面初始化策略：先访问闲鱼首页或 seller 首页，再访问 `https://login.taobao.com/member/login.jhtml` 初始化登录上下文，最后进入目标发布或商品管理页。当前账号已开通鱼小铺，多库存相关操作优先使用 seller 工作台；普通发布页仍可作为无库存要求的 fallback。`listing publish` 用于发布新商品。真实发布必须传入 `--confirm-real-publish`，并且必须提供标题、描述、价格、库存和至少一张本地图片路径；遇到登录、滑块、验证码、风控、权限不足、缺少字段、找不到发布按钮或发布后没有平台确认时只记录结构化失败，不伪造成功。

`python main.py web` 会启动本地管理页面，提供总览、自动发货配置、自动重新上架配置、新商品发布和任务记录。页面参考 `xianyu-auto-reply` 的管理台布局，但保留为轻量静态前端和 Python 标准库 HTTP API，不迁入 React/FastAPI/MySQL/Redis。页面不会展示 Cookie/API Key；真实重新上架和真实发布都需要在页面中显式勾选确认。

## 配置与默认关闭项

复制 `.env.example` 为 `.env` 后再填入真实配置。`.env`、Cookie、SQLite 运行库、买家信息、发货库存和真实重新上架任务都不应提交。

关键开关：

- `MODEL_BASE_URL=https://api-inference.modelscope.cn/v1` 与 `MODEL_NAME=deepseek-ai/DeepSeek-V4-Pro`：默认使用 ModelScope 的 OpenAI 兼容接口；真实 `API_KEY` 只写入本地 `.env`。
- `LLM_ENABLE_SEARCH=false`：默认不发送供应商特定的联网搜索扩展参数。
- `COOKIE_REFRESH_ENABLED=true`：默认每 10 分钟调用登录态续期接口合并 Set-Cookie，减少 `_m_h5_tk` 令牌过期导致的掉线；Session 过期、滑块或风控仍需人工重新登录。
- `AUTO_REPLY_ENABLED=true`：控制普通买家聊天是否进入 LLM 自动回复；这是全局总闸，实际只会回复本地已配置自动化的商品。付款完成消息仍由 `AUTO_DELIVERY_ENABLED` 单独控制。
- `NO_BARGAIN_MODE=true`：价格意图默认不砍价。买家询问优惠、折扣、预算、砍价、包邮或其他降价诉求时，程序直接回复固定拒绝降价话术，不调用价格 LLM Agent；只有显式设为 `false` / `0` / `no` / `off` 时，才恢复旧的 `PriceAgent` 议价策略。
- `AUTO_DELIVERY_ENABLED=false`：自动发货默认关闭。确认商品发货配置、库存和测试订单后，才在本地 `.env` 改成 `true`；即使总闸开启，没有启用发货配置的商品也不会自动发货。
- `AUTO_CONFIRM_DELIVERY_ENABLED=false`：闲鱼订单侧自动确认发货默认关闭。开启后，程序会在预设发货内容发送成功后调用闲鱼无物流确认发货接口；如果平台返回已发货，也按成功处理。
- `AUTO_RELIST_ENABLED=false`：发货后自动重新上架默认关闭；即使商品已配置 `listing auto-relist set`，未打开该开关也不会触发。
- `XIANYU_RELIST_API=`：可选的真实重新上架 mtop API 名称。没有稳定接口证据时保持为空；代码只提供签名调用边界，不硬编码未知接口。
- `AUTO_RELIST_ALLOW_PLAYWRIGHT=false`：默认不允许自动记录浏览器重新上架需求；开启后仍不会直接点击页面。
- `AUTO_RELIST_CONFIRM_PLAYWRIGHT=false`：发货后自动重新上架的真实浏览器点击确认开关；只有同时允许 Playwright 且该开关为 `true` 时，后台 hook 才会创建真实执行器。
- `AUTO_RELIST_SCREENSHOT_DIR=data/relist-screenshots`：授权浏览器路径保存页面证据的本地目录，默认不提交。
- `AUTO_RELIST_PLAYWRIGHT_HEADLESS=true`：重新上架浏览器执行器是否无头运行；也兼容旧的 `PLAYWRIGHT_HEADLESS`。
- `AUTO_RELIST_MANAGEMENT_URL=`：可选覆盖重新上架 Playwright 目标页。鱼小铺多库存排查可设为 `https://seller.goofish.com/?site=COMMONPRO#/seller-item/goods-manage`；普通重新发布 fallback 为空即可使用 `www.goofish.com/publish?itemId=...&editScene=rePutOn`。
- `AUTO_PUBLISH_URL=`：可选覆盖新商品发布 Playwright 目标页。鱼小铺发布可设为 `https://seller.goofish.com/?site=COMMONPRO#/seller-item/publish`；为空时使用普通 `www.goofish.com/publish`。
- `AUTO_PUBLISH_SCREENSHOT_DIR=data/publish-screenshots`：发布新商品浏览器路径保存页面证据的本地目录，默认不提交。
- `AUTO_PUBLISH_PLAYWRIGHT_HEADLESS=true`：发布新商品浏览器执行器是否无头运行；也兼容旧的 `PLAYWRIGHT_HEADLESS`。

普通聊天自动回复只对已配置商品生效：商品必须存在启用的发货配置，或存在启用的自动重新上架配置；未配置商品不会获取商品详情、不会进入 LLM，也不会发送自动回复。

商品知识库使用本地 Markdown 文件维护，默认路径是 `data/item_knowledge/<item_id>.md`，例如 `data/item_knowledge/1030573156061.md`。自动回复生成前会把当前商品的 Markdown 知识库附加到商品信息后面，要求模型优先依据商品信息和知识库回答；如果商品信息和知识库都没有明确答案，应回复“这个我确认一下，稍后回复你”，不要编造。`ITEM_KNOWLEDGE_DIR` 可覆盖知识库目录，`ITEM_KNOWLEDGE_MAX_CHARS` 控制单个商品注入 prompt 的最大字符数。

遇到兜底回复或明显不确定回复时，程序会把问题追加到 `UNKNOWN_QUESTIONS_PATH`，默认是 `data/unknown_questions.jsonl`。每行包含时间、商品 ID、会话 ID、用户问题、触发原因、机器人回复和意图，便于后续人工 review 后补进对应商品的 Markdown 知识库。该文件属于本地运行数据，不应提交。

启用自动发货后，程序会监听“我已付款，等待你发货”“等待卖家发货”等付款完成消息，解析订单号、商品 ID、买家和会话，再按商品配置发货。未配置启用发货内容的商品会直接跳过，不会拉取订单详情或发送任何内容。同一订单已经写入 `sent` 日志后会跳过重复发送；如果 `AUTO_CONFIRM_DELIVERY_ENABLED=true` 且该订单尚无 `platform_confirmed` 或 `platform_already_delivered` 日志，程序会继续尝试在闲鱼订单侧确认无物流发货。`data` 库存会按订单购买数量先预占，发送成功后标记 `sent`，发送失败时保留为 `failed_retryable` 以便同一订单重试继续使用原 key。发货内容发送成功但平台确认发货失败时，结果会记录为 `sent_confirm_failed` 和 `platform_confirm_failed`，不会重复发送内容，也不会触发发货后自动重新上架；下次遇到同一订单付款消息时会只重试平台确认。发货成功后，如果同时开启 `AUTO_RELIST_ENABLED=true` 且该商品存在启用的 `auto-relist` 配置，程序会创建重新上架任务并记录目标库存；带目标库存的重新上架请求即使商品状态显示为 `active`，也会继续执行补库存/重新上架动作，不会用 `already_active` 早退。当 `AUTO_CONFIRM_DELIVERY_ENABLED=true` 时，平台确认失败会阻止这一步。如果允许 Playwright 但没有设置 `AUTO_RELIST_CONFIRM_PLAYWRIGHT=true`，任务会停在需要授权浏览器执行的结构化结果，不会点击页面；失败只影响重新上架任务日志，不回滚已发货结果。

遇到 Cookie 失效、滑块、风控、账号归属不清或真实交易风险时，程序应记录原因并交给人工处理，不实现绕过逻辑。

## 测试与人工验收

默认验证只使用单元测试、fake/mocks 和 CLI 帮助命令，不需要真实闲鱼账号：

```bash
python -m py_compile main.py XianyuApis.py XianyuAgent.py context_manager.py xianyu_qr_login.py utils/xianyu_utils.py services/messages/*.py services/delivery/*.py services/listing/*.py
python -m pytest -q
python main.py --help
python main.py web --help
python main.py delivery --help
python main.py delivery inventory --help
python main.py listing --help
```

人工验收需要用户明确提供账号授权后再做：

1. `python main.py --qr-login` 刷新 Cookie。
2. `python main.py` 启动自动回复并验证一条买家咨询。
3. 使用测试订单或用户确认的真实订单验证一次幂等发货。
4. 对用户确认的已发布商品执行重新上架或确认 `already_active` 跳过，并检查 `listing_jobs` 记录。
5. 对用户确认的新商品执行 `listing publish --confirm-real-publish`，确认浏览器路径会完成闲鱼首页、淘宝登录页、普通发布页三段跳转，并检查页面确认结果。
6. `python main.py web` 能打开本地管理页面，发货配置、自动上架配置、发布表单和任务表能正常读写本地 API。

## 开发原则

- 先迁移自动回复，再扩展自动发货和重新上架。
- 实现前必须先定位两个参考项目中的既有实现，禁止凭空重写。
- 从 `xianyu-auto-reply` 迁移时只保留业务算法和协议细节，替换掉重后台依赖。
- SQLite 是 MVP 唯一持久化存储。
- 所有发货和重新上架动作必须可关闭、可重试、可审计、可幂等。
- `data` 类型发货必须先在 SQLite 事务中按订单数量预占对应库存行，不能在发送成功后才消费库存。
- 风控、滑块验证、Cookie 失效时停止自动动作，记录原因并交给人工处理。
