# Front Desk UX specification

This document is the acceptance reference for the Dashboard and Planning client
actions.  It applies to Arabic RTL and English LTR at desktop (1440 x 900) and
tablet (1024 x 768) sizes.  Phone layouts are deliberately outside the first
release.

## Shared context and states

- Property and hotel business date are shared between Dashboard and Planning.
- A business-day cell represents the property's configured noon-to-noon window.
- The last successful payload remains visible while a background refresh runs or
  fails.  Loading, empty, stale, error, selected, and refreshing states must not
  change the user's filters or scroll position.
- Operational identifiers, room numbers, dates, and monetary values use Western
  digits in both languages.

### Layout variants

| Variant | Direction | Header and controls | Operational body |
|---|---|---|---|
| Arabic desktop | RTL, Arabic labels | Title begins at the logical start; property/date and actions wrap from the logical end | Six KPI columns where space permits; floor labels and room column freeze at the logical start |
| Arabic tablet | RTL, Arabic labels | Controls wrap into labelled rows with no truncated action text | KPI grid reduces to two columns; the 224 px room column remains frozen and the date tape scrolls |
| English desktop | LTR, English labels | Same information order, mirrored through logical properties | Six KPI columns where space permits; room and floor column freezes at the left |
| English tablet | LTR, English labels | Controls wrap without changing tab order | Two-column KPIs and a horizontally scrollable date tape |

The visual implementation is the reference layout: no separate markup fork is
allowed for Arabic, English, desktop, or tablet.

### Data-state matrix

| State | Existing snapshot | Required presentation | Interaction |
|---|---|---|---|
| Initial loading | None | Centred progress indicator and polite status text | Controls remain labelled; no false zero values |
| Empty | Successful, no rooms/results | Purpose-specific empty message | Keep property/date and filter controls available |
| Refreshing | Last successful snapshot | Non-blocking progress text and unchanged content | Preserve focus, filters, selection, collapse state and scroll |
| Stale | Last successful snapshot after failure | Warning banner, last-updated time and Retry | All actions retain the displayed snapshot's property/date context |
| Error | No successful snapshot | Error message and Retry | Property/date can be corrected without a reload |
| Selected | Valid room/date or reservation | Visible focus/selection outline in addition to state color | Enter/Space performs the same action as pointer/touch |
| Attention | Warning or danger queue entry | Icon, text, count and severity border | Opens the exact record set used for the count |

## Room status model

| Layer | Values | Presentation |
|---|---|---|
| Occupancy | Vacant, Reserved, Occupied, Checkout | Primary text label and semantic border/background |
| Capacity | Out of order, House use | Persistent blocking badge; never encoded only by color |
| Housekeeping | Clean, Dirty, Inspected | Secondary badge with icon and text alternative |
| Attention | Arrival, Departure, DND, Maintenance, Wake-up | Individually labelled alert badges |

Capacity blockers take visual precedence, but do not hide occupancy or secondary
states.  Combined states such as occupied + dirty + DND remain visible.

## Dashboard layout

1. A wrapping header contains title, labelled property and business-date inputs,
   Planning, New Reservation, manual refresh, and the last-updated timestamp.
2. Primary KPIs show arrivals, departures, in-house rooms, occupancy, ADR, and
   RevPAR. Secondary KPIs show inventory and housekeeping counts.
3. The attention queue is ordered by severity and time. Every item opens a list
   filtered to the same property and business date.
4. The room board uses collapsible floor sections. Room buttons show room/type,
   guest or reservation reference when permitted, arrival/departure, and every
   applicable status layer.

## Planning layout

1. A wrapping toolbar contains property, start date, 7/14/30-day range, filters,
   legend, refresh, and the read-only native Gantt fallback.
2. The room/floor column is frozen while dates scroll horizontally. Floors are
   explicit groups and every active room is shown, including empty rooms.
3. Selecting an empty room/date opens a one-night draft reservation prefilled at
   the business-day boundaries. Selecting a reservation opens the existing form;
   confirmed and in-house changes remain amendment-only.
4. The tape never exposes drag or resize interactions.

## Accessibility and responsive acceptance

- Interactive controls are semantic buttons/inputs, keyboard reachable, at least
  44 px in their touch dimension, and have a visible focus indicator.
- Text contrast is at least 4.5:1; large text and UI boundaries are at least 3:1.
- Every icon has a text alternative and color is never the sole status cue.
- Refresh and error changes use polite live announcements without moving focus.
- Logical CSS properties mirror the layouts in RTL. At 1024 px the toolbar wraps,
  the Planning tape scrolls horizontally, and no Arabic label clips or overlaps.

## Semantic design tokens

Custom Front Desk surfaces share the `--hotel-*` token namespace. Text and
surface tokens are independent from occupancy/status tokens. The neutral canvas,
panel borders, brand accent, focus treatment, and four-pixel radius derive from
Odoo's backend theme variables. Operational pages use flat grey hierarchy rather
than bright white card fields: shadows, glossy gradients, and hover lift are not
part of the Front Desk visual language. Spacing follows 4/8 px increments and
every interactive target has a 44 px minimum touch dimension. Status colors are
restrained and always paired with a translated label or icon and screen-reader
text.
