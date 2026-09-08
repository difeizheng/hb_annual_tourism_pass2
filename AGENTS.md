# hb_annual_tourism_pass2 — 湖北旅游年卡分析工具

Streamlit 单体应用（`app/main.py`，3400+ 行）：年卡对比选卡 + 景点知识图谱 + 行程规划。
数据管道在 `src/`（解析/清洗/对齐/图谱），行程规划子模块在 `src/trip_planner/`。

## 命令

- 运行 App：`run_streamlit.bat`（Windows）或 `streamlit run app/main.py --server.port=8551`；必须从项目根目录启动，`main.py:18` 有 `sys.path.insert` hack，import 路径是 `src.xxx` / `src.trip_planner.xxx`
- 测试：项目根目录 `pytest tests/`（无配置文件，纯默认发现；含 map_server e2e，155 项）。e2e 会复用已在 18793 监听的 map_server，没有则自启并在测后关闭；覆盖率用 `pytest --cov=src`
- 重新解析原始年卡数据到 `data/`：跑 `src/pipeline.py`（各阶段产物：cleaned_spots.json / spot_coordinates.json / knowledge_graph.json / alignment_report.json）

## 约定

- **依赖无清单**：`.gitignore` 忽略 `*.toml`，所以没有 requirements.txt/pyproject.toml；新环境需手动装 streamlit、pandas、plotly、requests、openpyxl、pytest。不要试图提交 toml 文件，会被 ignore
- **密钥走 Streamlit secrets**：`app/.streamlit/secrets.toml`（被 gitignore，本地文件），key 名：`amap_js_key`（前端渲染）、`amap_web_key`（地理编码/POI）、`llm_api_key`/`llm_api_base`（OpenAI 兼容接口，默认 dashscope）。读取统一用 `st.secrets`，勿改环境变量方案
- **data/reviews/ 文件名是景点名 MD5**：`review_scraper.py:69`，按文件名找不到景点时需反向对照 MD5
- **地图服务是独立子进程**：`app/map_server.py` 由 main.py 启动（避免 Streamlit 线程问题），日志在 `data/map_server.log`，调试地图先看这个日志。
  首选端口 18793 若被 Windows 排除端口区段（Hyper-V/WSL 动态保留，重启漂移）挡住会自动向后协商，实际端口写在 `data/map_server.port`，main.py 与 e2e 从该文件读取
- LLM 客户端封装在 `src/trip_planner/llm_client.py`，OpenAI 兼容协议，新功能复用它而非直接 requests

## 禁区与坑

- `raw_data/`（4 张年卡的原始 xlsx+json）是上游交付物，只读不改；解析逻辑变了也只改 `src/parser.py` 后重跑管道
- `app/.streamlit/secrets.toml` 含真实 API key，绝不提交、不硬编码进源码
- `.gitignore` 忽略 `*.txt`、`*.bat`、`data/trip_plans/`（运行时产物/本地笔记）；根目录的 `zdf.txt`、`_coord_check.txt` 是未跟踪的调研笔记，勿删
- `data/` 下 json 均为管道生成物，改源码后重跑生成而非手改；`static/` 是地图前端产物
- **chat_planner 页三处坑**（f238aac 修过，别回退）：① 从 `app/` 下文件取项目根用 `dirname(dirname(__file__))` 两级，三级会跳出根导致 spot_coordinates.json 读空 → 行程 0 天；② `pass_coverage` 的函数名是 `compute_pass_coverage`；③ `num_days` 可能是字符串，core 层已做 `int(float(str()))` 强转；④ 页面代码**禁止 `from app.main import …`**——Streamlit 以 `__main__` 跑 main.py，二次 import 会整页重执行，报 StreamlitDuplicateElementId；共用函数放 `app/map_html.py`（地图 HTML 构建/落盘，自包含无 st 依赖）
- **无头冒烟容器 stub 陷阱**（行程导入页踩过，e7751cf）：`st.columns` 返回 MagicMock 元素时，容器内 `col.button()` 恒真值——同帧两个按钮全"被点击"（解析后立刻被清除分支抹掉 session），且无任何报错；容器必须真 stub（button 返回 False、selectbox 返回业务值）。另：单测 mock 掉 `chat_completion` 只验证解析逻辑，返回值形状（Response vs dict）与 secrets 读取路径必须留一次真实调用验收（e67eb75 两处真 bug 都是 mock 掩盖的）。详见知识库 `patterns/streamlit-无头UI冒烟固定套路.md`
