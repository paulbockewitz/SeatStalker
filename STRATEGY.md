---
name: SeatStalker
last_updated: 2026-06-16
---

# SeatStalker Strategy

## Target problem

Travelers who book flights late often end up separated from companions or stuck in suboptimal
seats. Seat availability changes unpredictably and airline sites don't notify you — so most
people just accept what they have, not realizing their target seats opened and closed while
they weren't watching.

## Our approach

Build a zero-login seat monitoring tool that works across many airlines by separating
airline-specific data fetching (adapters) from airline-agnostic seat matching and alerting
(core). Each new airline only requires a new adapter; the core never changes. Reliability —
zero missed seat opens — is the primary bar.

## Who it's for

**Primary:** Travelers with existing bookings — they're hiring SeatStalker to watch for
specific seat openings and alert them the moment those seats become available, so they can
grab them before someone else does.

## Key metrics

- **Missed alerts** — number of times a target seat opened and no email was sent; target: zero; measured: log file + manual spot-check
- **Alert latency** — time from seat opening to email delivered; should be ≤ 1 check interval (30 min); measured: log timestamps
- **Airlines covered** — number of airlines with a working, tested adapter; measured: repo adapters list
- **Adapter add time** — wall-clock time from "I have a data source" to "SeatStalker supports this airline"; target: < 1 day

## Tracks

### Core reliability
Ensure every supported airline's adapter fails loudly (never silently), logs cleanly, and
retries or exits with a clear error code so no seat open is ever silently missed.

_Why it serves the approach:_ Reliability is the primary success signal — a tool that misses
openings is worse than no tool.

### Adapter architecture
Define and stabilize a clean Python adapter interface so Delta, Iberia, and future airlines
all implement the same two-method contract; airline-specific code never leaks into core.

_Why it serves the approach:_ The adapter boundary is what makes multi-airline expansion
cheap — once the interface is locked, adding an airline is a contained, isolated task.

### Airline coverage
Add and validate each new airline adapter (Iberia next) so SeatStalker is useful for more
travelers' actual itineraries.

_Why it serves the approach:_ Coverage is the lagging metric — it only grows after
reliability and architecture are solid.

## Not working on

- Printing Press CLIs as a requirement (adapters can use any data source — CLI, Python sidecar, API)
- Login-based access (booking reference + passenger name — first and/or last depending on the airline — only)
- Seat purchasing or booking changes (monitor and alert only)
- Web UI or hosted service (self-hosted tool, no SaaS)
