# Filter Behavior Lock

This document captures the current filter interaction contract in `site/app.js`.
Refactors should preserve these behaviors exactly unless a deliberate product change is approved.

## Top Row Buttons

### Type button row (`toggleType`)

1. Fresh-load default state is implicit all (`allTypesMode = true`, `selectedTypes` empty) with no active top-row type chip highlight.
2. Clicking `all` from implicit all switches to explicit all (`allTypesMode = false`, `selectedTypes` contains every type).
3. Clicking `all` from explicit all toggles back to implicit all.
4. Clicking a specific type while in all mode exits all mode and selects only that type.
5. Clicking a selected type removes it.
6. If the last selected type is removed, the state snaps back to all mode.

### Year button row (`toggleYear`)

1. Fresh-load default state is implicit all (`allYearsMode = true`, `selectedYears` empty) with no active top-row year chip highlight.
2. Clicking `all` from implicit all switches to explicit all (`allYearsMode = false`, `selectedYears` contains every visible year).
3. Clicking `all` from explicit all toggles back to implicit all.
4. Clicking a specific year while in all mode exits all mode and selects only that year.
5. Clicking a selected year removes it.
6. If the last selected year is removed, the state snaps back to all mode.
7. Year values outside `currentVisibleYears` are ignored.

## Dropdown Menus

### Type dropdown (`toggleTypeMenu`)

1. Clicking `all` in the open menu from a partial draft selection updates the type draft state to all mode and clears draft explicit selections.
2. Clicking `all` while already in all mode (or while explicit-all is selected) toggles to non-all mode with an empty set.
3. Clicking a specific type while in all mode exits all mode and draft-selects all types except the clicked type.
4. Clicking a selected type removes it from the draft; clicking an unselected type adds it to the draft.
5. Invalid types are ignored.

### Year dropdown (`toggleYearMenu`)

1. Clicking `all` in the open menu from a partial draft selection updates the year draft state to all mode and clears draft explicit selections.
2. Clicking `all` while already in all mode (or while explicit-all is selected) toggles to non-all mode with an empty set.
3. Clicking a specific year while in all mode exits all mode and draft-selects all visible years except the clicked year.
4. Clicking a selected year removes it from the draft; clicking an unselected year adds it to the draft.
5. Invalid/non-visible years are ignored.

### Done button behavior (`finalizeTypeSelection`, `finalizeYearSelection`)

1. Clicking `Done` commits the current draft state into live filter state.
2. Type selection does not auto-compress explicit-all into implicit-all after `Done`; explicit-all remains explicit.
3. Year selection still compresses explicit-all into implicit-all after `Done`.
4. Closing a dropdown without `Done` (outside tap or toggling closed) discards the draft and keeps live filters unchanged.

### Dropdown apply timing

1. Menu option clicks update menu UI only (checkmarks/label text) and do not rerender dashboard cards.
2. Dashboard cards rerender only when committed state changes (for example on `Done`, top-row buttons, clear, reset).

### Mobile type action button

1. On narrow/mobile layout, the type action button shows `Select All` (enabled) in implicit-all mode.
2. Pressing `Select All` on mobile switches type state to explicit all.
3. When not in implicit-all mode, the button label is `Clear` and restores implicit all when pressed.

## Summary Cards and Card-Level Filters

### Summary type cards

1. Summary type cards delegate to the same behavior as top row type buttons.

### Year metric cards and summary metric cards

1. Each year card has a single-select metric toggle (distance, time, elevation).
2. Clicking an active metric on a year card clears that year’s metric.
3. Summary metric active state is derived:
   - exactly one metric is selected across all visible years where that metric is filterable
   - any mismatch or partial applicability disables the active summary state
4. Clicking an active summary metric clears that metric for all visible years.
5. Clicking an inactive summary metric applies it to all visible years where filterable.

### Frequency fact cards and metric chips

1. Frequency fact cards are global single-select toggles.
2. Clicking an active fact clears it; clicking an inactive fact sets it active.
3. Non-filterable facts are disabled.
4. Frequency metric chips (distance, time, elevation) are single-select toggles for the frequency card heatmaps.
5. Top summary metric active state requires both:
   - exactly one derived year metric is active across visible year cards (existing rule), and
   - the frequency metric chip selection matches that same metric.
6. Clicking an inactive summary metric applies that metric to all eligible year cards and the frequency metric chip (if filterable).
7. Clicking an active summary metric clears that metric from all eligible year cards and clears the frequency metric chip.
8. Non-filterable metric chips are unavailable/unclickable and show a disabled-state appearance.
9. Clicking any summary metric card clears the active frequency fact selection (for example `Most Active Month`).

## Reset Behavior

### Reset-all enabled state

`Reset All` is enabled whenever any of the following are true:

1. Types are not in all mode.
2. Years are not in all mode.
3. Any year metric selection exists.
4. A frequency fact selection exists.
5. A frequency metric chip selection exists.

### Reset-all click

Clicking `Reset All` restores default state:

1. Type and year filters reset to all mode.
2. Year metric, frequency fact, and frequency metric chip selections are cleared.
3. Visible/filterable metric/fact tracking maps are cleared.
4. Summary hover-cleared visual state is cleared.
5. On narrow/mobile layouts, the page scroll position resets to top and card horizontal scroll restoration is skipped (cards return to far-left).

## Card Scroll State

1. Each year/frequency card uses a stable scroll key per logical card identity.
2. On full dashboard rerender, horizontal `scrollLeft` is restored for matching cards when possible.

## Trends Card

The "Trends" labeled card row renders below "Activity Frequency" in both the
combined-types branch and the single-type branch of `update()`, side by side
with "Cumulative Progress" in a shared `.labeled-card-row-pair` container
(cards keep content width; the content rail is sized at 1250px so the pair
fits side by side in every Trends view, wrapping only on narrower viewports).

### Chip behavior (`buildTrendsCard`)

1. Granularity chips (`Weekly | Monthly | Yearly`) are single-select with always
   exactly one active; clicking the active chip is a no-op (no toggle-off).
2. Metric chips (`Activities | Distance | Time | Elevation`) follow the same
   always-one-active rule. Metrics with a zero total for the current selection
   render as unavailable (same treatment as frequency metric chips).
3. Chip clicks rerender only the trends chart, never the full dashboard.
4. Defaults are `Monthly` + `Distance`. When `Distance` is unavailable the
   displayed metric falls back to the first available metric (ultimately
   `Activities`), without overwriting the stored selection.
5. Selections persist across type/year filter changes and unit toggles via
   `selectedTrendsGranularity` / `selectedTrendsMetricKey` in `init()`; only
   user chip clicks (`source === "card"`) update stored state.

### Chart behavior

1. Bars are computed client-side from `payload.aggregates` via
   `bucketAggregatesByPeriod`; weekly buckets use `weekOfYear` within the
   activity's own year and respect the configured week start.
2. Weekly/monthly views render one row per visible year (newest first) with a
   shared max scale across rows; yearly renders a single chronological row.
3. Multi-type selections stack bar segments per type using type accent colors.
4. Future periods in the current year render as void slots (no baseline).
5. Bar tooltips show the period label, activity total with per-type breakdown,
   and non-zero Distance/Time/Elevation totals in the active units.

### Reset-all interaction

1. `Reset All` restores granularity/metric defaults, and non-default trends
   state enables the `Reset All` button (`isDefaultTrendsState`).

## Cumulative Progress Card

The "Cumulative Progress" labeled card row renders side by side with "Trends"
in a shared `.labeled-card-row-pair` container in both the combined-types
branch and the single-type branch of `update()`.

### Chip behavior (`buildProgressCard`)

1. Metric chips (`Activities | Distance | Time | Elevation`) are single-select
   with always exactly one active; clicking the active chip is a no-op.
   Unavailable metrics follow the shared unavailable-chip treatment.
2. Default metric is `Distance`, falling back to the first available metric
   without overwriting the stored selection.
3. Chip clicks rerender only the progress chart, never the full dashboard.
4. The selection persists across type/year filter changes and unit toggles via
   `selectedProgressMetricKey`; only chip clicks (`source === "card"`) update
   stored state. `Reset All` restores the default and non-default state
   enables the button (`isDefaultProgressState`).

### Chart behavior

1. One SVG polyline per visible year over a shared Jan–Dec axis
   (`buildCumulativeSeriesByYear`), cumulative from daily aggregates; years
   with a zero total for the active metric are omitted.
2. The current calendar year's line ends at today; prior years extend flat to
   year end. The current year renders with a heavier stroke.
3. Line colors cycle the fallback palette by year order (newest first); the
   legend lists each year with its running total in the active units.
4. Weekly hover strips show "Through <date>" cumulative values per year via
   the shared tooltip system.
