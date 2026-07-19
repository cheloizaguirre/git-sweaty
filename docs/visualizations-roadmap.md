# Visualizations Roadmap & Session Status

Status record for the aggregate-visualization work. Last updated: 2026-07-19.

## Ground rules (unchanged throughout)

- All new visualizations are computed **client-side in `site/app.js`** from the
  daily aggregates already in `site/data.json`. No changes to pipeline scripts,
  GitHub workflows/triggers, data files, or the `dashboard-data` branch.
- The project stays a static GitHub Pages site; pushing `site/` changes to
  `main` deploys via the existing `pages.yml` trigger.

## Completed

| Commit | Feature |
| --- | --- |
| `9944796` | **Trends card** — weekly/monthly/yearly bar charts (granularity + metric chips, one row per year, stacked type segments) |
| `20ff791` | **Cumulative Progress card** — year-over-year cumulative SVG line chart, paired side-by-side with Trends; rail widened to 1250px |
| `30d4f2c` | **Records card** — best day/week/month per metric (stateless) |
| `26333b9` | **Training Load card** — rolling 7-day total + 28-day avg (÷4) lines on a continuous epoch-day timeline, full-width row below Records |
| `be594a3` | **Streaks & Gaps card** — longest/current active-week streak (grace for in-progress week), longest/current break in days; stateless, reuses Records styles |
| `9a89bd4` | **Seasonality card** — 12-bar average per calendar month over active years only (hiatus years don't drag averages); paired side-by-side with Streaks & Gaps (`statsPairRow`) |
| `ba43b9d` | **Hilliness card** — stateless monthly elevation÷distance line (ft/mi or m/km), gaps break the line, isolated months as dots; half-rail width to pair with Average Speed |
| `9efe4d4` | **Average Speed card** — stateless monthly distance÷moving-time line (mph or km/h), paired side-by-side with Hilliness (`ratioPairRow`) |
| `ea3746b` | **Per-activity cards** — pipeline adds `distance`/`moving_time`/`elevation_gain` to `activities[]`; Ride Records + Distance Distribution pair and Distance vs Elevation scatter; rows hide on payloads without the fields |

Key code locations in `site/app.js`:

- `bucketAggregatesByPeriod` / `trendsPeriodForDate` — shared weekly/monthly/
  yearly bucketing (per-type breakdowns, week-start aware). Reused by Trends,
  Progress (totals), and Records.
- `buildTrendsCard`, `buildProgressCard`, `buildRecordsCard` — card builders,
  modeled on `buildStatsOverview` (the Activity Frequency card).
- `buildCumulativeSeriesByYear`, `computeRecords` — pure computation helpers.
- `loadEpochDay` / `loadDateFromEpochDay` / `computeRollingLoadSeries` —
  epoch-day timeline + sliding-window rolling totals; `buildLoadCard` renders
  it (reuses `progress-gridline` / `progress-axis-label` /
  `progress-hover-strip` / `progress-legend*` CSS; only line + container
  styles are load-specific).
- Wiring: both branches of `update()` (combined-types and single-type) append,
  after the Activity Frequency row: a `.labeled-card-row-pair` flex container
  holding Trends + Cumulative Progress, then the Records row, then the
  Training Load row.
- State: `selectedTrendsGranularity`, `selectedTrendsMetricKey`,
  `selectedProgressMetricKey`, `selectedLoadMetricKey` in `init()`; persisted only on chip clicks
  (`source === "card"`), included in `isDefaultFilterState()` and Reset All.

Conventions established:

- Chips reuse `.more-stats-metric-chip` styling (`trends-chip` class);
  single-select, always exactly one active (no toggle-off), unavailable
  metrics get the shared unavailable treatment.
- Chip clicks rerender only their own card, never the full dashboard.
- Tooltips go through the shared `attachTooltip(el, text)` system.
- Every card gets a scroll key (`setCardScrollKey`) and a section in
  `docs/filter-behavior-lock.md`.
- Contract tests extract the pure JS functions by regex and run them in node
  (pattern from `tests/test_frequency_layout_contract.py`); see
  `tests/test_trends_card_contract.py`, `tests/test_progress_card_contract.py`,
  `tests/test_records_card_contract.py`.
- Width budget: `--dashboard-content-rail-width` =
  `max(summary grid, 1250px)`; progress SVG width is capped by a contract test
  so the pair always fits side by side (weekly Trends ≈ 640px + progress card
  ≈ 590px + 14px gap ≤ 1250px).

## Verification workflow

- `node --check site/app.js`
- `python3 -m unittest discover -s tests` — note: `test_utils.py` has one
  **pre-existing** failure under Python 3.10 (fractional-seconds parsing);
  CI uses 3.11 where it passes. Everything else should be green.
- Visual check: `./scripts/dev_dashboard.sh`
- A throwaway headless DOM-stub harness (node, no jsdom) was used in-session
  to render `app.js` against the real `data.json` from the `dashboard-data`
  branch and assert card structure + recomputed totals. It lived outside the
  repo; recreate on demand (stub document/window/fetch, run app.js in a vm
  context, query the stub tree).

## Remaining backlog (from the original plan, in suggested order)

1. **Indoor/outdoor share** — Ride vs VirtualRide share per month
   (stacked area). REJECTED: user is not interested in this card
2. **Start-hour × weekday punch card** — refinement of the hour matrix. REJECTED: user is not interested in this card
3. *(Requires small pipeline change — still no workflow/data changes:)* add
   `distance`/`moving_time`/`elevation_gain` to `activities[]` items in
   `generate_heatmaps.py::_load_activities` to enable per-activity records
   (longest single ride, distribution histogram) and a distance-vs-elevation
   scatter.

## Session log

- 2026-07-18: Trends, Cumulative Progress (side-by-side pair, wider rail),
  and Records cards implemented, tested, and committed. All work verified in
  the dev dashboard by Marcelo. Nothing pushed yet as of this writing.
- 2026-07-19: Training Load card (`26333b9`) implemented, tested (14 contract
  tests, harness 25/25 incl. independent rolling-total recomputation), and
  committed after Marcelo's dashboard review. Marcelo rejected the
  indoor/outdoor share and punch card backlog items and redefined streaks as
  active-week streaks with breaks in days. Next up: Streaks & gaps.
- 2026-07-19 (later): Streaks & Gaps card (`be594a3`) implemented, tested
  (13 contract tests, harness 16/16 incl. independent streak/break
  recomputation), and committed after Marcelo's dashboard review. Note:
  local dev serves `app.js?v=__APP_VERSION__` (placeholder only replaced at
  deploy), so browsers can cache a stale app.js — hard refresh when a new
  card "doesn't show". Next up: Seasonality profile.
- 2026-07-19 (later): Seasonality card (`9a89bd4`) implemented with
  active-month-only averaging (Marcelo's pick), tested (13 contract tests,
  harness 19/19), and committed after dashboard review. Next up: Hilliness
  trend, sized half-rail so the Average Speed trend can pair beside it.
- 2026-07-19 (later): Hilliness card (`ba43b9d`) implemented, tested
  (11 contract tests, harness 16/16 incl. independent ratio/segment
  recomputation), and committed after dashboard review. Next up: Average
  Speed trend, paired beside Hilliness.
- 2026-07-19 (later): Average Speed card (`9efe4d4`) implemented, tested
  (11 contract tests, harness 15/15), and committed after dashboard review.
  Client-side backlog exhausted; remaining item is the per-activity fields
  pipeline change enabling single-ride records, histogram, and scatter.
- 2026-07-19 (later): Per-activity fields + three cards (`ea3746b`); roadmap
  complete apart from rejected items. QoL round started: metric default,
  year-selector behavior, card layout reorganization.
