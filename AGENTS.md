# hb_annual_tourism_pass2 — 湖北旅游年卡分析工具

Streamlit 应用：年卡对比选卡 + 景点知识图谱 + 行程规划。
数据管道在 `src/`（解析/清洗/对齐/图谱），行程规划子模块在 `src/trip_planner/`。

**UI 架构（2026-09 重构后）**：`app/main.py`（~970 行）只是骨架——imports/数据加载/地图构建 helper/侧边栏/页面 dispatch。所有页面在 `app/page_modules/*.py`（**不能叫 `app/pages/`**——Streamlit 会把 entry 旁的 `pages/` 目录当多页应用，在侧边栏自动生成英文导航）：

- 页面函数模式：`def render_xxx_page(ctx)`，首行 `globals().update(ctx)` 注入 main 命名空间，**页面模块不写任何业务 import、禁止 `from app.main import …`**（二次 import 会整页重执行）；main.py 侧 `render_xxx_page(dict(globals()))` 调用
- 导航 6 项：🗺️ 地图探索（含「📈 数据洞察」view=原数据总览页）/ 🎫 年卡对比 / 💡 选卡助手 / 🌿 季节指南 / 🗓️ 规划中心 / 🧳 我的行程
- **规划中心**（`app/planning_hub.py`）是唯一的行程生成入口：radio 切换 表单规划/对话规划/周末出发/单日路线/粘贴导入/✏️编辑器 六模式（不用 st.tabs，避免后台 tab 白算）
- **我的行程**（`app/page_modules/my_trips_page.py`）= 草稿区（session selected_trip_spots）+ 行程仓库（全部已保存 plan：详情/地图/✏️跳编辑器/删除）
- **统一行程 schema v2**（`src/trip_planner/plan_schema.py`）：所有来源（manual/chat/import/day_route/weekend）落同一结构，`plan_manager.load_plan` 自动迁移旧格式；day 级额外信息（酒店/交通/时间线）存 `meta.day_extras`；保存统一走 `plan_manager.save_days_plan`；编辑器是共享组件 `app/plan_editor.py`（`render_plan_editor`，state_prefix/widget_prefix 区分多实例）

## 命令

- 运行 App：`run_streamlit.bat`（Windows）或 `streamlit run app/main.py --server.port=8551`；必须从项目根目录启动，`main.py:18` 有 `sys.path.insert` hack，import 路径是 `src.xxx` / `src.trip_planner.xxx`
- 测试：项目根目录 `pytest tests/`（无配置文件，纯默认发现；含 map_server e2e，198 项）。e2e 会复用已在 18793 监听的 map_server，没有则自启并在测后关闭；覆盖率用 `pytest --cov=src`
- UI 冒烟（python 直跑，非 pytest）：`tests/smoke_hub_repo_ui.py`（规划中心+行程仓库对真实磁盘 plan 渲染）、`tests/smoke_import_editor_ui.py`、`tests/smoke_day_route_ui.py`
- 重新解析原始年卡数据到 `data/`：跑 `src/pipeline.py`（各阶段产物：cleaned_spots.json / spot_coordinates.json / knowledge_graph.json / alignment_report.json / name_aliases.json / canonicalize_report.json）

## 约定

- **依赖无清单**：`.gitignore` 忽略 `*.toml`，所以没有 requirements.txt/pyproject.toml；新环境需手动装 streamlit、pandas、plotly、requests、openpyxl、pytest。不要试图提交 toml 文件，会被 ignore
- **密钥走 Streamlit secrets**：`app/.streamlit/secrets.toml`（被 gitignore，本地文件），key 名：`amap_js_key`（前端渲染）、`amap_web_key`（地理编码/POI）、`llm_api_key`/`llm_api_base`（OpenAI 兼容接口，默认 dashscope）。读取统一用 `st.secrets`，勿改环境变量方案
- **data/reviews/ 文件名是景点名 MD5**：`review_scraper.py:69`，按文件名找不到景点时需反向对照 MD5；景点被 canonicalizer 改名后旧 MD5 会失去关联（可用 name_aliases.json 反查）
- **名称归一化（Step 2.5）**：`src/canonicalizer.py` 把「张公山寨(青山区)」「多乐台球（限1次）」「武汉花博汇」这类变体并入基础名（897→810 唯一名），同时重映射 spot_coordinates.json；括号内容是**位置身份**（店/码头/景区/公园/馆…）的不并（爱蹦蹦床馆两个店、两江游览四个码头是不同实体）。唯一名数变化会影响所有统计口径，不是 bug
- **高德地理编码会返回「城市中心伪装答案」**：查不到的 POI 常返回 `formatted_address=湖北省XX市`（无区县、城市中心坐标），直接采信会把点打到几十/几百公里外。用 geocode 结果前校验响应的 city/district 字段，或与已有坐标做距离交叉验证
- **地图服务是独立子进程**：`app/map_server.py` 由 main.py 启动（避免 Streamlit 线程问题），日志在 `data/map_server.log`，调试地图先看这个日志。
  首选端口 18793 若被 Windows 排除端口区段（Hyper-V/WSL 动态保留，重启漂移）挡住会自动向后协商，实际端口写在 `data/map_server.port`，main.py 与 e2e 从该文件读取
- LLM 客户端封装在 `src/trip_planner/llm_client.py`，OpenAI 兼容协议，新功能复用它而非直接 requests

## 禁区与坑

- `raw_data/`（10 张年卡的原始 xlsx+json）是上游交付物，只读不改；解析逻辑变了也只改 `src/parser.py` 后重跑管道
- `app/.streamlit/secrets.toml` 含真实 API key，绝不提交、不硬编码进源码
- `.gitignore` 忽略 `*.txt`、`*.bat`、`data/trip_plans/`（运行时产物/本地笔记）；根目录的 `zdf.txt`、`_coord_check.txt` 是未跟踪的调研笔记，勿删
- `data/` 下 json 均为管道生成物，改源码后重跑生成而非手改；`static/` 是地图前端产物
- **chat_planner 历史坑**（f238aac 修过）：① 从 `app/` 下文件取项目根用 `dirname(dirname(__file__))` 两级；② `pass_coverage` 的函数名是 `compute_pass_coverage`；③ `num_days` 可能是字符串，core 层已做 `int(float(str()))` 强转；④ 共用无 st 依赖函数放 `app/map_html.py`
- **跨页导航跳转**：页面里不能直接 `ss.nav_page = …`（nav radio 已在侧边栏实例化，同帧赋值抛 StreamlitAPIException）；用 pending 模式——页面设 `ss._nav_pending = 目标页`，main.py 在建 radio 之前 pop 并赋给 `nav_page`。hub 模式同理预置 `ss.ph_mode`
- **抽取搬迁代码后必须做静态名字解析校验**：原样搬运的代码块可能引用已不存在的变量；用 ast 收集页面函数内 LOAD vs（赋值名+main globals+builtins）比对，MISSING 必须 NONE
- **改 import 的模块必须重启 Streamlit**（模块缓存）；且重启前先杀干净旧进程——Windows 允许同端口多进程 LISTENING，旧进程会用 stale sys.modules 服务浏览器报 ImportError
- **无头冒烟容器 stub 陷阱**（行程导入页踩过，e7751cf）：`st.columns` 返回 MagicMock 元素时，容器内 `col.button()` 恒真值——同帧两个按钮全"被点击"（解析后立刻被清除分支抹掉 session），且无任何报错；容器必须真 stub（button 返回 False、selectbox 返回业务值）。另：单测 mock 掉 `chat_completion` 只验证解析逻辑，返回值形状（Response vs dict）与 secrets 读取路径必须留一次真实调用验收（e67eb75 两处真 bug 都是 mock 掩盖的）。详见知识库 `patterns/streamlit-无头UI冒烟固定套路.md`
- **模块改进清单（08e5b86）**：① 季节指南分层列表用 session flag 按需渲染（每层首 15 个+「展开剩余 N 个」按钮）——st.expander 折叠也会全量服务端渲染，不能当性能手段；② 选卡助手 Step 5 出行月份，当季必去数按 `min(hits*1.5, 15)` 加分；③ 草稿区持久化 `data/trip_draft.json`（main.py try/finally 每 rerun 落盘，新会话冷启动恢复；恢复时过滤非 dict/无 name 条目）；④ 行程仓库：来源筛选+名称搜索、删除二次确认、日列表 3 天后折叠（**st.expander 不能嵌套**，仓库项本身在 expander 内，折叠用 `st.toggle`）；⑤ 规划中心 LLM 模式（对话/导入）key 未配置时前置 warning
