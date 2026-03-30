# Asset Detail UI Spec v1

## Purpose

`Asset Detail` is a dedicated chart-first screen for one symbol.

It is not a replacement for:
- `Command Center`
- `Market Intel`

It exists to answer a different question:

- `What is this symbol doing over time?`
- `How has it behaved across multiple windows?`
- `What events, signals, and execution states explain the move?`

## Current Implementation Status

Implemented now:
- dedicated `#asset/{code}` route
- chart-first layout with large primary chart area
- `1D / 5D / 1M / 3M / 6M / YTD / 1Y`
- `Line / Candles` toggle
- `MA20 / MA50` toggle
- OHLC + volume hover detail
- separate volume panel below price chart
- normalized compare overlay using a second ticker
- latest news and execution context panels
- asset-specific backend APIs

Still not implemented:
- peer compare presets
- indicator drawer beyond `MA20 / MA50`
- advanced crosshair/header sync
- earnings/financials/analyst modules

The design target is closer to a `Yahoo Finance style chart view`, but adapted for AlphaTrade:
- keep chart exploration familiar
- keep execution and risk context attached
- avoid turning the main cockpit into a retail chart app

## Role In Product IA

Recommended screen roles:

- `Command Center`: operator cockpit, event/risk/actionability first
- `Market Intel`: sector/market structure first
- `Asset Detail`: symbol timeline and chart exploration first
- `Backtest`: strategy evaluation first

Navigation rule:

- clicking a symbol in `Command Center`
- clicking a candidate in `Market Intel`
- clicking a symbol in `Market`

should open `Asset Detail` for that symbol.

Recommended route:

- `#asset/005930`

Fallback if current hash router stays simple:

- `#asset?code=005930`

## Screen Goal

The page must let a user understand in under 10 seconds:

1. current price and directional move
2. whether the move is intraday noise or multi-period trend
3. whether the move has catalyst support
4. whether the engine has a signal
5. whether trading is blocked, active, or recently executed

## Layout

### 1. Header Bar

Left:
- stock name
- stock code
- market
- sector

Center:
- current price
- absolute change
- percent change
- market session badge

Right:
- watchlist/focus action later
- quick jump back to `Command Center`
- quick jump back to `Market Intel`

### 2. Range Selector

Primary controls:
- `1D`
- `5D`
- `1M`
- `3M`
- `6M`
- `YTD`
- `1Y`

Optional later:
- `3Y`
- `5Y`
- `MAX`

Behavior:
- active range must be visually prominent
- range change should update chart without full page refresh
- `1D` and `5D` should use intraday/intraperiod data if available
- `1M+` should use aggregated bars

### 3. Main Price Chart

Core behavior:
- Yahoo-style wide chart area
- hover tooltip with date/time, OHLC, volume
- color by direction
- subtle area fill under line
- stronger line than current default charts

Required overlays:
- separate volume panel below price
- previous close line for `1D`
- moving averages toggle
- line/candles toggle

Visual rules:
- rising range: green line/fill
- falling range: red line/fill
- neutral: gray line/fill

### 4. Period Return Strip

Directly above or below chart:

- `1D`
- `5D`
- `1M`
- `3M`
- `6M`
- `1Y`

Each cell shows:
- arrow `▲ / ▼ / •`
- signed percent
- green/red/gray tone

This is where directional scan speed matters most.

### 5. Key Stats Rail

Right side on desktop, below chart on mobile:

- market cap later if available
- day range
- 52w range later if available
- average volume
- relative volume
- volatility proxy
- latest signal
- signal strength

AlphaTrade-specific additions:
- latest event type
- latest order status
- risk block status
- stale-data status

### 6. Catalyst Timeline

Below chart:

- recent news
- disclosure items
- event-scan triggers
- TradingView alerts

Each item shows:
- time
- source/type
- short title
- tone

The user should be able to correlate chart movement with catalysts quickly.

### 7. Execution & Risk Panel

This is the AlphaTrade differentiator versus Yahoo-style retail views.

Required blocks:
- latest signal summary
- latest order timeline
- position status
- risk gate result
- session state

Possible statuses:
- eligible
- blocked
- watching
- executed

### 8. Mini Comparison Section

Implemented in current UI:

- compare ticker search using stock code/name search
- normalized performance overlay in line mode
- primary vs compare labels above chart

Next recommended step:

- sector ETF/index proxy
- market index proxy
- sector peers

Purpose:
- show whether the move is idiosyncratic or sympathy-driven

## Data Requirements

### Frontend Inputs

Recommended APIs:

- `GET /asset/{code}/overview`
- `GET /asset/{code}/chart?range=1D`
- `GET /asset/{code}/chart?range=5D`
- `GET /asset/{code}/period-returns`
- `GET /asset/{code}/events`
- `GET /asset/{code}/execution-context`

### Minimum Response Groups

`overview`
- code
- name
- market
- sector
- current price
- change
- change pct
- session

`chart`
- timestamp
- open
- high
- low
- close
- volume

`period-returns`
- 1D
- 5D
- 1M
- 3M
- 6M
- YTD
- 1Y

`events`
- time
- type
- source
- title
- url

`execution-context`
- latest signal
- signal strength
- candidate lane
- recent order status
- filled qty
- risk violations
- stale flag

## Interaction Rules

- symbol changes should preserve selected range if sensible
- compare ticker should preserve selected range
- enabling compare should default chart mode to `line`
- clearing compare should keep current symbol and chart range intact
- mobile should stack `header -> period strip -> chart -> stats -> catalysts -> execution`
- desktop should use `chart left / stats right`
- every major status uses arrow + color + text, not color alone

## Visual Direction

Do not make it look like the current dashboard cards.

Visual goals:
- chart-first
- lower chrome
- wider whitespace around chart
- stronger numeric hierarchy
- lighter supporting copy
- fewer hard borders

Avoid:
- chip walls
- dense alert piles above chart
- equal emphasis on all metrics

## Implementation Plan

### Phase 1

- create `AssetDetail.tsx`
- add route handling in `App.tsx`
- support symbol navigation from existing pages
- render:
  - header
  - range selector
  - main chart
  - period return strip
  - basic right rail

### Phase 2

- add catalyst timeline
- add execution context panel
- add peer/sector comparison strip

### Phase 3

- add chart overlays and indicator toggles
- add saved symbol focus/watch behavior

## Success Criteria

The screen succeeds if:

- a user can recognize trend direction faster than in current `Market` or `Trend`
- a user can connect chart move to news/event/execution in one place
- the cockpit remains operationally focused because chart exploration moved out of it

## Recommendation

Implement `Asset Detail` before adding more complexity to `Command Center`.

Reason:
- chart exploration belongs here
- operator action belongs in the cockpit
- separating them improves both screens
