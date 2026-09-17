# Graph Report - hb_annual_tourism_pass2  (2026-09-17)

## Corpus Check
- 103 files · ~380,536 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 867 nodes · 1737 edges · 52 communities (44 shown, 8 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 68 edges (avg confidence: 0.72)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7bef471a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_integration.py
- chat_planner.py
- calculate_seasonal_score
- plan_multi_city
- classify_spot
- MapHandler
- _build_trip_map_html
- render_weekend_page
- pass_comparator.py
- test_plan_schema.py
- main.py
- test_map_server_e2e.py
- align_spots
- build_graph
- pipeline.py
- route_optimizer.py
- itinerary_importer.py
- haversine_distance
- cleaner.py
- test_plan_editor.py
- save_days_plan
- render_day_route_page
- plan_editor.py
- smoke_hub_repo_ui.py
- test_day_route_planner.py
- llm_client.py
- render_trip_planner_page
- get_opening_hours
- geocoder.py
- day_route_planner.py
- Col
- regeocode.py
- normalize_level
- aggregate_spot_reviews
- strip_area_from_name
- all_stops
- budget_planner.py
- clean_spot_name
- auto_assigner.py
- TestNormalize
- hb_annual_tourism_pass2 — 湖北旅游年卡分析工具
- SS
- TestSaveWithCoords
- TestResolve
- TestResolveSingle
- _resolve_map_port
- run_pipeline
- compute_pass_coverage
- SS
- src/__init__.py
- trip_planner/__init__.py

## God Nodes (most connected - your core abstractions)
1. `calculate_seasonal_score()` - 36 edges
2. `_make_spot()` - 26 edges
3. `_make_graph()` - 23 edges
4. `save_days_plan()` - 20 edges
5. `plan_multi_city()` - 19 edges
6. `DayRoute` - 19 edges
7. `haversine_distance()` - 19 edges
8. `migrate_plan()` - 18 edges
9. `_build_trip_map_html()` - 16 edges
10. `render_trip_planner_page()` - 15 edges

## Surprising Connections (you probably didn't know these)
- `render_data_overview_page()` --calls--> `build_graph()`  [INFERRED]
  app/pages/data_overview_page.py → src/graph_builder.py
- `render_map_explore_page()` --calls--> `batch_geocode()`  [INFERRED]
  app/pages/map_explore_page.py → src/geocoder.py
- `render_my_trips_page()` --calls--> `search_nearby_hotels()`  [INFERRED]
  app/pages/my_trips_page.py → src/trip_planner/nearby_search.py
- `render_my_trips_page()` --calls--> `search_nearby_restaurants()`  [INFERRED]
  app/pages/my_trips_page.py → src/trip_planner/nearby_search.py
- `render_my_trips_page()` --calls--> `generate_route_options()`  [INFERRED]
  app/pages/my_trips_page.py → src/trip_planner/route_optimizer.py

## Import Cycles
- None detected.

## Communities (52 total, 8 thin omitted)

### Community 0 - "test_integration.py"
Cohesion: 0.06
Nodes (41): _build_map_html(), Generate AMap HTML with markers., render_data_overview_page(), render_map_explore_page(), category_distribution(), city_distribution(), global_stats(), level_distribution() (+33 more)

### Community 1 - "chat_planner.py"
Cohesion: 0.06
Nodes (41): _build_and_reply(), _clarify_question(), _critical_missing(), _finalize_intent_defaults(), _handle_user_message(), Chat-based trip planner page (Streamlit UI layer). Logic lives in…, # NOTE: app/chat_planner.py → parent.parent = project root; dirname×3 lands, State machine: intake → (clarify)×N → build plan. (+33 more)

### Community 2 - "calculate_seasonal_score"
Cohesion: 0.09
Nodes (20): calculate_seasonal_score(), get_seasonal_recommendations(), Seasonal recommendation engine with multi-tier scoring., Calculate seasonal relevance score (0-5) and reason string., Generate tiered seasonal recommendations. Returns dict with season info,…, check_seasonal_availability(), _find_alternatives(), Check seasonal availability of spots and suggest alternatives. (+12 more)

### Community 3 - "plan_multi_city"
Cohesion: 0.08
Nodes (25): find_holiday_by_name(), is_off_day(), merge_off_blocks(), date, Static China holiday tables for 2025-2026 (no API dependency). Used by…, True if d is a rest day: statutory holiday OR normal weekend (not a make-up…, Merge consecutive off-days within [start, end] into contiguous blocks.…, All contiguous blocks of a named holiday in the year, e.g. name='国庆'. (+17 more)

### Community 4 - "classify_spot"
Cohesion: 0.08
Nodes (14): classify_spot(), Spot classifier: auto-categorize spots based on name keywords and rules., Classify a spot into categories. Returns {"category": str, "sub_category": str,…, parse_notes(), parse_spot_rules(), parse_usage_limit(), Rule parser: extract structured rules from usage_limit and notes fields., Parse notes field into structured rules. Extracts: - child_policy: children… (+6 more)

### Community 5 - "MapHandler"
Cohesion: 0.10
Nodes (23): _bind_with_fallback(), main(), MapHandler, Standalone map server for the tourism pass app. Run this separately from…, Try PREFERRED_PORT first, then scan outward. Windows reserved ranges…, SimpleHTTPRequestHandler, _cache_path(), _delay() (+15 more)

### Community 6 - "_build_trip_map_html"
Cohesion: 0.10
Nodes (28): Build day-toggle map HTML via _build_trip_map_html and stash URL., _render_map(), _render_trip_result(), _build_trip_map_html(), Backward-compat wrapper — real impl in app/map_html.py., Backward-compat wrapper — real impl in app/map_html.py., _save_map_html(), _build_trip_map_html() (+20 more)

### Community 7 - "render_weekend_page"
Cohesion: 0.12
Nodes (24): _generate_amenities(), render_weekend_page(), find_city_hotel(), find_parking_for_spot(), plan_meals_for_day(), Amenity planning: hotels (city-stay), meals, parking per multi-city day plan.…, Nearest parking lot POI for a spot., Pick ONE hotel for a whole city block, near the spot centroid. (+16 more)

### Community 8 - "pass_comparator.py"
Cohesion: 0.10
Nodes (25): render_pass_compare_page(), compute_city_pass_heatmap(), compute_complementarity(), compute_cost_performance_ranking(), compute_exclusive_spots(), compute_optimal_combinations(), compute_route_feasibility(), compute_savings() (+17 more)

### Community 9 - "test_plan_schema.py"
Cohesion: 0.15
Nodes (25): build_plan(), _carry_identity(), _migrate_imported(), migrate_plan(), _migrate_quick(), _migrate_v2(), normalize_day(), normalize_stop() (+17 more)

### Community 10 - "main.py"
Cohesion: 0.13
Nodes (21): get_unique_spots_with_coords(), Streamlit app: knowledge graph with AMap visualization., Build unique spot list with coordinates, one record per spot., render_pass_assistant_page(), render_season_guide_page(), plan_budget(), Generate 3 budget plans within the given budget. Args: budget: total budget in…, build_pass_info() (+13 more)

### Community 11 - "test_map_server_e2e.py"
Cohesion: 0.14
Nodes (22): fixture, _base(), map_server(), port(), E2E tests for app/map_server.py — real HTTP against a real server instance. The…, Argument validation only — no real AMap call., Actual port: data/map_server.port written by the server after binding, falling…, Probe the argument-validation branch: a live map_server answers 400. (+14 more)

### Community 12 - "align_spots"
Cohesion: 0.15
Nodes (11): align_spots(), compute_similarity(), normalize_name(), Entity aligner: match same spots across different passes using fuzzy matching., Compute similarity score between two spot names. Uses multiple strategies and…, Align spots across passes. Returns: { "canonical_spots": [{"canonical_name":…, Normalize name for comparison., Tests for the aligner module. (+3 more)

### Community 13 - "build_graph"
Cohesion: 0.16
Nodes (16): build_graph(), export_neo4j_cypher(), graph_to_json(), load_graph(), MultiDiGraph, Graph builder: construct knowledge graph using NetworkX (with Neo4j export…, Convert NetworkX graph to JSON-serializable dict., Save graph to JSON file. (+8 more)

### Community 14 - "pipeline.py"
Cohesion: 0.12
Nodes (16): get_or_create_data(), load_data(), Load and process all data., Load from cache if exists, otherwise run pipeline., cache_data, get_pass_names(), load_all_passes(), load_json() (+8 more)

### Community 15 - "route_optimizer.py"
Cohesion: 0.16
Nodes (14): build_day_route(), Real driving route (polyline/distance/duration) through ordered stops. Falls…, compute_route(), DayRoute, _fallback_route(), Route optimization using nearest-neighbor algorithm and AMap driving API., Compute straight-line distances when API fails., Call AMap driving API to get actual road distances and polyline. (+6 more)

### Community 16 - "itinerary_importer.py"
Cohesion: 0.15
Nodes (20): _extract_json_array(), _load_custom_stops(), parse_itinerary_text(), _poi_search(), (coord, rest) if name mentions a city/county, else (None, name). rest = name…, AMap text search for one stop name. anchor: {lng,lat} nearby-city hint — biases…, Geocode stop names: pass pool -> custom stops -> AMap POI. Two deterministic…, Resolve ONE stop name -> {lng,lat,source} or None. Same deterministic chain as… (+12 more)

### Community 17 - "haversine_distance"
Cohesion: 0.17
Nodes (16): _month_to_season(), Multi-city trip orchestration: city ordering + per-city day allocation. Sits…, Pre-select spots by seasonal score × duration value to fit daily bins. First-…, _select_spots_for_capacity(), _transfer_km(), estimate_play_duration(), Play duration estimation by category, sub_category, and level., Estimate play duration in hours for a spot. Priority: sub_category > category >… (+8 more)

### Community 18 - "cleaner.py"
Cohesion: 0.16
Nodes (12): clean_all_spots(), clean_spot_record(), extract_pass_info(), get_unique_spots(), Data cleaner: normalize spot records from all passes., Clean all spot records., Get unique spots by name (before entity alignment)., Extract pass metadata from filename. E.g. "大武汉景区旅游年卡_200元" -> {"name":… (+4 more)

### Community 19 - "test_plan_editor.py"
Cohesion: 0.20
Nodes (13): anchor_for(), _move_cb(), Nearest resolved coord before stop (day_num, idx): same-day earlier stops…, selectbox on_change: move stop (dn, idx) to the chosen day., _fake_st(), dict, Unit tests for the shared plan editor helpers + unified save path., _SS (+5 more)

### Community 20 - "save_days_plan"
Cohesion: 0.18
Nodes (15): _ensure_dir(), generate_plan_id(), list_plans(), load_plan(), Plan CRUD: save, load, list, delete trip plans as JSON files. All plans…, Save plan to data/trip_plans/<id>.json. Returns plan ID. Plans carrying a…, Load a plan by ID (legacy formats auto-migrated to unified v2). Returns None if…, List all saved plans sorted by updated_at descending. (+7 more)

### Community 21 - "render_day_route_page"
Cohesion: 0.18
Nodes (9): _poi_search(), Build + save map HTML via map_html, return map_server URL., AMap text search -> [{name, lng, lat, category, address}]., _render_day_route_map(), render_day_route_page(), estimate_custom_play_hours(), Rough play duration for a custom stop from its AMap type string., Recorder (+1 more)

### Community 22 - "plan_editor.py"
Cohesion: 0.26
Nodes (11): render_itinerary_import_page(), init_editor_state(), Idempotent init of the editor's UI state keys., Clear editor UI state (e.g. after parse/clear on the import page)., Map + per-day editor + save for the day dicts at ss[days_key]. days: [{day_num,…, _render_add_stop(), _render_edit_form(), render_plan_editor() (+3 more)

### Community 23 - "smoke_hub_repo_ui.py"
Cohesion: 0.15
Nodes (5): Col, dict, MagicMock, Recorder, SS

### Community 24 - "test_day_route_planner.py"
Cohesion: 0.23
Nodes (11): build_day_timeline(), optimize_stop_order(), Return stops in visit order. optimize=True runs nearest-neighbor from origin;…, Interleave play durations and real drive legs into a timed schedule. Returns {…, nearest_neighbor_optimize(), Greedy nearest-neighbor TSP approximation. O(n^2), fine for n<20., _fake_route(), test_optimize_keeps_manual_order_when_disabled() (+3 more)

### Community 25 - "llm_client.py"
Cohesion: 0.31
Nodes (10): compute_price_value_score(), generate_spot_recommendation(), get_fallback_recommendation(), _llm_recommendation(), LLM-powered spot recommendation and price value scoring., Rule-based fallback when LLM is unavailable., 0-10 score based on price vs level. Higher level + lower price = higher score., Generate recommendation. Tries LLM first, falls back to rule-based. (+2 more)

### Community 26 - "render_trip_planner_page"
Cohesion: 0.27
Nodes (8): Main entry for the 💬 对话规划 page. Args: spots_with_coords: all unique spots with…, render_chat_planner_page(), render_trip_planner_page(), Shared editor bound to ed_* session keys (set by 我的行程's ✏️ 编辑)., _render_editor_mode(), render_planning_hub(), get_all_passes_info(), Get summary info for all passes (name, spot count, price, etc).

### Community 27 - "get_opening_hours"
Cohesion: 0.24
Nodes (9): _build_weekend_timeline(), Build timeline with actual driving times between spots., get_opening_hours(), Return (open_hour, close_hour) for a category., build_day_timeline(), _format_time(), Build day-by-day timeline with estimated time slots., Format hour and minute as HH:MM string. (+1 more)

### Community 28 - "geocoder.py"
Cohesion: 0.20
Nodes (9): batch_geocode(), geocode_one(), load_coordinates(), AMap geocoding: convert spot names to coordinates., Load cached coordinates., Save coordinates to cache., Geocode a single address via AMap REST API., Geocode multiple spots in batches. Args: spots: list of {spot_name, city, area}… (+1 more)

### Community 29 - "day_route_planner.py"
Cohesion: 0.36
Nodes (9): delete_custom_stop(), load_custom_stops(), Single-day route planner core — pure functions, no Streamlit dependencies.…, Return {name: stop dict}., Insert or update a custom stop. Returns the stored dict., save_custom_stops(), _stop_to_dict(), upsert_custom_stop() (+1 more)

### Community 30 - "Col"
Cohesion: 0.20
Nodes (4): Col, MagicMock, Column element stub: every widget returns a safe business value., Recorder

### Community 31 - "regeocode.py"
Cohesion: 0.33
Nodes (8): find_conflict_spots(), geocode_poi(), load_coordinates(), main(), Re-geocode spots with imprecise coordinates using enhanced addresses and POI…, Try POI search first, fall back to geo with detailed address., Find spot names that share coordinates with >= threshold other spots., save_coordinates()

### Community 32 - "normalize_level"
Cohesion: 0.36
Nodes (3): normalize_level(), Normalize attraction level to standard format (A1-A5, A0, None)., TestNormalizeLevel

### Community 33 - "aggregate_spot_reviews"
Cohesion: 0.31
Nodes (8): aggregate_spot_reviews(), _empty_review(), _extract_sentiment(), load_all_reviews(), Aggregate real visitor reviews from data/reviews/ directory., Load all review JSON files from REVIEWS_DIR., Aggregate reviews for a specific spot. Returns: { "review_count": int,…, Extract pros/cons from review texts using keyword matching.

### Community 34 - "strip_area_from_name"
Cohesion: 0.43
Nodes (3): Remove area suffix from spot name. Returns (cleaned_name, area_from_name). E.g.…, strip_area_from_name(), TestStripAreaFromName

### Community 35 - "all_stops"
Cohesion: 0.33
Nodes (6): skipif, all_stops(), Flatten all stops with day_num attached (for map rendering)., Every plan file currently on disk must migrate without exceptions and produce a…, test_real_legacy_files_migrate(), test_summary_and_all_stops()

### Community 36 - "budget_planner.py"
Cohesion: 0.40
Nodes (4): Budget planner: generate optimal spending plans within a given budget., estimate_trip_cost(), Estimate total trip cost: driving, accommodation, tickets, food., Calculate complete trip cost breakdown. Args: total_distance_km: total driving…

### Community 37 - "clean_spot_name"
Cohesion: 0.47
Nodes (3): clean_spot_name(), Clean spot name to canonical form., TestCleanSpotName

### Community 38 - "auto_assigner.py"
Cohesion: 0.40
Nodes (5): assign_spots_to_days(), cluster_by_proximity(), Auto-assign spots to trip days based on geographic proximity., Assign spots to days based on geographic proximity. Strategy: 1. Cluster by…, Greedy spatial clustering. Spots within max_distance_km of cluster center go…

### Community 40 - "hb_annual_tourism_pass2 — 湖北旅游年卡分析工具"
Cohesion: 0.40
Nodes (4): hb_annual_tourism_pass2 — 湖北旅游年卡分析工具, 命令, 禁区与坑, 约定

### Community 45 - "_resolve_map_port"
Cohesion: 0.50
Nodes (4): map_server 绑定失败会自动向后换端口，并把实际端口写进 data/map_server.port；这里优先读文件，退回默认值。, Launch the standalone map server as a subprocess., _resolve_map_port(), _start_map_server()

### Community 46 - "run_pipeline"
Cohesion: 0.50
Nodes (3): Execute the full data processing pipeline., run_pipeline(), TestPipeline

### Community 47 - "compute_pass_coverage"
Cohesion: 0.50
Nodes (3): compute_pass_coverage(), Calculate pass coverage and savings for selected spots., For each selected spot, find which passes cover it and compute savings. Args:…

## Knowledge Gaps
- **3 isolated node(s):** `命令`, `约定`, `禁区与坑`
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `save_days_plan()` connect `save_days_plan` to `chat_planner.py`, `_build_trip_map_html`, `render_weekend_page`, `test_plan_schema.py`, `main.py`, `itinerary_importer.py`, `test_plan_editor.py`, `render_day_route_page`, `plan_editor.py`, `render_trip_planner_page`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `calculate_seasonal_score()` connect `calculate_seasonal_score` to `haversine_distance`, `main.py`, `budget_planner.py`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Why does `compute_route()` connect `route_optimizer.py` to `render_weekend_page`, `main.py`, `itinerary_importer.py`, `plan_editor.py`, `day_route_planner.py`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `save_days_plan()` (e.g. with `render_trip_planner_page()` and `render_weekend_page()`) actually correct?**
  _`save_days_plan()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `命令`, `约定`, `禁区与坑` to the rest of the system?**
  _3 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_integration.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05714285714285714 - nodes in this community are weakly interconnected._
- **Should `chat_planner.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06253652834599649 - nodes in this community are weakly interconnected._