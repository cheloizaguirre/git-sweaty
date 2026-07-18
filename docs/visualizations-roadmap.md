# Visualizations Roadmap & Session Status

Status record for the aggregate-visualization work. Last updated: 2026-07-18.

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

Key code locations in `site/app.js`:

- `bucketAggregatesByPeriod` / `trendsPeriodForDate` — shared weekly/monthly/
  yearly bucketing (per-type breakdowns, week-start aware). Reused by Trends,
  Progress (totals), and Records.
- `buildTrendsCard`, `buildProgressCard`, `buildRecordsCard` — card builders,
  modeled on `buildStatsOverview` (the Activity Frequency card).
- `buildCumulativeSeriesByYear`, `computeRecords` — pure computation helpers.
- Wiring: both branches of `update()` (combined-types and single-type) append,
  after the Activity Frequency row: a `.labeled-card-row-pair` flex container
  holding Trends + Cumulative Progress, then the Records row.
- State: `selectedTrendsGranularity`, `selectedTrendsMetricKey`,
  `selectedProgressMetricKey` in `init()`; persisted only on chip clicks
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

1. **Rolling 7-day / 28-day load** — rolling distance/time line chart
   (training-load proxy). Client-side from daily aggregates; can reuse the
   progress card's SVG approach.
2. **Streaks & gaps** — longest/current active-day streak, longest break;
   possibly a streak highlight on existing heatmaps.
3. **Seasonality profile** — average volume per calendar month across years.
4. **Hilliness trend** — elevation gain per km by month.
5. **Average speed trend** — distance ÷ moving time per week/month.
6. **Indoor/outdoor share** — Ride vs VirtualRide share per month
   (stacked area).
7. **Start-hour × weekday punch card** — refinement of the hour matrix.
8. *(Requires small pipeline change — still no workflow/data changes:)* add
   `distance`/`moving_time`/`elevation_gain` to `activities[]` items in
   `generate_heatmaps.py::_load_activities` to enable per-activity records
   (longest single ride, distribution histogram) and a distance-vs-elevation
   scatter.

## Session log

- 2026-07-18: Trends, Cumulative Progress (side-by-side pair, wider rail),
  and Records cards implemented, tested, and committed. All work verified in
  the dev dashboard by Marcelo. Nothing pushed yet as of this writing.
