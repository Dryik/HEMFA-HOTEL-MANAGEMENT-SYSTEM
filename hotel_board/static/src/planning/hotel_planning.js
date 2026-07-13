import {
    Component,
    onMounted,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import {
    actionWithFrontdeskContext,
    addIsoDays,
    asArray,
    asId,
    atNoon,
    errorMessage,
    formatCurrency,
    formatNumber,
    formatOperationalDateTime,
    formatUpdatedAt,
    formatWeekday,
    isoDate,
    refreshFailureViewState,
    westernDigits,
} from "../shared/frontdesk_utils";
import "../shared/frontdesk_state_service";

const REFRESH_INTERVAL_MS = 60_000;
const ALLOWED_DAY_COUNTS = [7, 14, 30];
const DAY_WIDTH_PX = 100;
const ROOM_COLUMN_WIDTH_PX = 224;
const RESERVATION_LANE_HEIGHT_REM = 4.2;

const EMPTY_FILTERS = Object.freeze({
    floor_ids: [],
    room_type_ids: [],
    room_statuses: [],
    hk_statuses: [],
    reservation_states: [],
    agency_ids: [],
    group_ids: [],
    guest_query: "",
    room_query: "",
    reference_query: "",
});

const STATUS_LABELS = {
    vacant: _t("Vacant"),
    reserved: _t("Reserved"),
    occupied: _t("Occupied"),
    checkout: _t("Checkout"),
    clean: _t("Clean"),
    dirty: _t("Dirty"),
    inspected: _t("Inspected"),
    out_of_order: _t("Out of Order"),
    house_use: _t("House Use"),
};

const ALERT_LABELS = {
    arrival: _t("Arrival"),
    departure: _t("Departure"),
    dnd: _t("Do Not Disturb"),
    wakeup: _t("Wake-up Call"),
    maintenance: _t("Maintenance"),
    balance: _t("Balance Due"),
};

function cssToken(value, fallback = "unknown") {
    const token = String(value || "").toLowerCase().replace(/[^a-z0-9_-]/g, "_");
    return token || fallback;
}

function cloneEmptyFilters() {
    return Object.fromEntries(
        Object.entries(EMPTY_FILTERS).map(([key, value]) => [key, Array.isArray(value) ? [] : value])
    );
}

function normaliseFilters(filters = {}) {
    const normalised = cloneEmptyFilters();
    for (const key of Object.keys(normalised)) {
        if (Array.isArray(normalised[key])) {
            normalised[key] = asArray(filters[key]);
        } else {
            normalised[key] = String(filters[key] || "");
        }
    }
    return normalised;
}

function dateDifference(start, end) {
    const startDate = isoDate(start);
    const endDate = isoDate(end);
    if (!startDate || !endDate) {
        return 0;
    }
    const toUtc = (value) => {
        const [year, month, day] = value.split("-").map(Number);
        return Date.UTC(year, month - 1, day);
    };
    return Math.round((toUtc(endDate) - toUtc(startDate)) / 86_400_000);
}

export function normaliseBar(bar, startDate, dayCount) {
    const rawStart = Number.isFinite(Number(bar.start_index))
        ? Number(bar.start_index)
        : dateDifference(startDate, bar.start_business_date || bar.start_datetime);
    const rawSpan = Math.max(
        1,
        Number(bar.span) ||
            dateDifference(
                bar.start_business_date || bar.start_datetime,
                bar.end_business_date || bar.end_datetime
            ) ||
            1
    );
    const clippedStart = Math.max(0, rawStart);
    const clippedEnd = Math.min(dayCount, rawStart + rawSpan);
    const span = Math.max(1, clippedEnd - clippedStart);
    return {
        ...bar,
        id: bar.id || bar.reservation_id,
        gridStart: clippedStart + 1,
        gridSpan: span,
        stateClass: cssToken(bar.state),
        guestName: bar.guest?.name || bar.guest_name || "",
        warnings: asArray(bar.warnings),
        warningLabels: asArray(bar.warnings).map(
            (warning) => warning?.label || warning?.key || String(warning || "")
        ),
    };
}

export function assignReservationLanes(bars) {
    const laneEnds = [];
    for (const bar of [...bars].sort(
        (left, right) => left.gridStart - right.gridStart || right.gridSpan - left.gridSpan
    )) {
        const start = bar.gridStart;
        let lane = laneEnds.findIndex((end) => end <= start);
        if (lane < 0) {
            lane = laneEnds.length;
        }
        bar.lane = lane;
        laneEnds[lane] = start + bar.gridSpan;
    }
    return Math.max(laneEnds.length, 1);
}

function normaliseRow(row, floor, startDate, dayCount) {
    const dayStatuses = asArray(row.day_statuses).map((status, index) => ({
        ...status,
        index: Number.isFinite(Number(status.index)) ? Number(status.index) : index,
        primaryClass: cssToken(status.primary_status),
        housekeepingClass: cssToken(status.hk_status),
        blockerClass: cssToken(status.capacity_blocker),
        alertTypes: asArray(status.alert_types),
    }));
    const dayStatusByIndex = Object.fromEntries(dayStatuses.map((status) => [status.index, status]));
    const reservations = asArray(row.reservations).map((bar) =>
        normaliseBar(bar, startDate, dayCount)
    );
    const laneCount = assignReservationLanes(reservations);
    return {
        ...row,
        id: row.id || row.room_id,
        name: row.name || row.room_name,
        floorId: asId(row.floor_id) || floor.id,
        floorName: row.floor_name || floor.name,
        roomTypeName: row.room_type?.name || row.room_type || "",
        occupancyClass: cssToken(row.occupancy_status),
        housekeepingClass: cssToken(row.hk_status),
        blockerClass: cssToken(row.capacity_blocker),
        alerts: asArray(row.alerts).map((alert) => ({
            ...alert,
            severityClass: cssToken(alert.severity, "info"),
        })),
        dayStatusByIndex,
        reservations,
        laneCount,
    };
}

export function normalisePlanning(raw = {}, requestedStartDate, requestedDayCount) {
    const meta = raw.meta || {};
    const startDate = meta.start_date || requestedStartDate;
    const dayCount = ALLOWED_DAY_COUNTS.includes(Number(meta.day_count))
        ? Number(meta.day_count)
        : requestedDayCount;
    let days = asArray(raw.days);
    if (!days.length && startDate) {
        days = Array.from({ length: dayCount }, (_, index) => ({
            date: addIsoDays(startDate, index),
            label: formatOperationalDateTime(addIsoDays(startDate, index)),
            weekday: "",
            index,
            is_today: false,
            is_business_date: index === 0,
        }));
    }
    days = days.map((day, index) => ({
        ...day,
        index: Number.isFinite(Number(day.index)) ? Number(day.index) : index,
        date: isoDate(day.date) || addIsoDays(startDate, index),
    }));
    const floors = asArray(raw.floors).map((floor, floorIndex) => ({
        ...floor,
        id: floor.id ?? `floor-${floorIndex}`,
        name: floor.name || _t("Unassigned Floor"),
        rows: asArray(floor.rows || floor.rooms).map((row) =>
            normaliseRow(row, floor, startDate, dayCount)
        ),
    }));
    return {
        version: raw.version || 1,
        meta: { ...meta, start_date: startDate, day_count: dayCount },
        properties: asArray(raw.properties),
        permissions: raw.permissions || {},
        days,
        filters: {
            applied: normaliseFilters(raw.filters?.applied),
            options: raw.filters?.options || {},
        },
        legend: raw.legend || {},
        floors,
        totals: raw.totals || {
            rooms: floors.reduce((total, floor) => total + floor.rows.length, 0),
            reservations: floors.reduce(
                (total, floor) =>
                    total + floor.rows.reduce((roomTotal, row) => roomTotal + row.reservations.length, 0),
                0
            ),
        },
        actions: raw.actions || {},
    };
}

export class HotelPlanning extends Component {
    static template = "hotel_board.HotelPlanning";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.frontdeskState = useService("hotel_frontdesk_state");
        this.tapeRef = useRef("tape");
        const stored = this.frontdeskState.get();
        const actionContext = this.props.action?.context || {};
        const actionParams = this.props.action?.params || {};
        const explicitPropertyId = asId(
            actionParams.property_id ||
                actionContext.default_property_id ||
                actionContext.property_id
        );
        const contextDayCount = Number(
            actionParams.day_count || actionContext.day_count || actionContext.default_day_count
        );
        this.state = useState({
            data: null,
            loading: true,
            refreshing: false,
            error: null,
            stale: false,
            updatedAt: null,
            ariaStatus: _t("Loading reservation planning."),
            propertyId:
                explicitPropertyId || stored.propertyId,
            startDate:
                actionParams.start_date ||
                actionContext.default_start_date ||
                actionContext.start_date ||
                actionContext.default_business_date ||
                actionContext.business_date ||
                stored.businessDate,
            dayCount: ALLOWED_DAY_COUNTS.includes(contextDayCount) ? contextDayCount : 14,
            filters: normaliseFilters(actionParams.filters || actionContext.filters),
        });
        this._request = null;
        this._requestSequence = 0;
        this._refreshTimer = null;
        this._lastAttemptAt = 0;
        this._destroyed = false;
        this._storedPropertyFallbackPending = Boolean(
            stored.propertyId && !explicitPropertyId
        );
        this._lastSuccessfulFilters = normaliseFilters(this.state.filters);
        this._onVisibilityChange = () => this.onVisibilityChange();

        onMounted(() => {
            this.loadData();
            this.startRefreshTimer();
            globalThis.document?.addEventListener("visibilitychange", this._onVisibilityChange);
        });
        onWillUnmount(() => {
            this._destroyed = true;
            this.stopRefreshTimer();
            globalThis.document?.removeEventListener("visibilitychange", this._onVisibilityChange);
            this._request?.abort?.(false);
        });
    }

    startRefreshTimer() {
        if (!this._refreshTimer) {
            this._refreshTimer = browser.setInterval(() => {
                if (!globalThis.document?.hidden) {
                    this.loadData({ background: true, preserveScroll: true });
                }
            }, REFRESH_INTERVAL_MS);
        }
    }

    stopRefreshTimer() {
        if (this._refreshTimer) {
            browser.clearInterval(this._refreshTimer);
            this._refreshTimer = null;
        }
    }

    onVisibilityChange() {
        if (globalThis.document?.hidden) {
            this.stopRefreshTimer();
            return;
        }
        this.startRefreshTimer();
        if (Date.now() - this._lastAttemptAt >= REFRESH_INTERVAL_MS) {
            this.state.stale = Boolean(
                this.state.updatedAt && Date.now() - this.state.updatedAt >= REFRESH_INTERVAL_MS * 2
            );
            this.loadData({ background: true, preserveScroll: true });
        }
    }

    async loadData({ background = false, preserveScroll = true } = {}) {
        const tape = this.tapeRef.el;
        const scrollPosition =
            preserveScroll && tape ? { left: tape.scrollLeft, top: tape.scrollTop } : null;
        this._request?.abort?.(false);
        const requestSequence = ++this._requestSequence;
        const requestedPropertyId = this.state.propertyId;
        const requestedStartDate = this.state.startDate;
        const requestedDayCount = this.state.dayCount;
        const requestedFilters = normaliseFilters(this.state.filters);
        const hadData = Boolean(this.state.data);
        this._lastAttemptAt = Date.now();
        this.state.loading = !hadData;
        this.state.refreshing = hadData;
        if (!background) {
            this.state.ariaStatus = _t("Refreshing reservation planning.");
        }
        try {
            this._request = this.orm.silent.call("hotel.frontdesk.workspace", "get_planning_window", [
                this.state.propertyId || false,
                this.state.startDate || false,
                this.state.dayCount,
                this.state.filters,
            ]);
            const raw = await this._request;
            if (this._destroyed || requestSequence !== this._requestSequence) {
                return;
            }
            const data = normalisePlanning(raw, this.state.startDate, this.state.dayCount);
            this.state.data = data;
            this.state.propertyId = asId(data.meta.property_id);
            this.state.startDate = data.meta.start_date;
            this.state.dayCount = data.meta.day_count;
            this._lastSuccessfulFilters = requestedFilters;
            this.frontdeskState.update({
                propertyId: this.state.propertyId,
                businessDate: data.meta.business_date || this.state.startDate,
            });
            this.state.error = null;
            this.state.stale = false;
            this.state.updatedAt = Date.now();
            this.state.ariaStatus = _t("Reservation planning updated.");
            if (scrollPosition) {
                browser.requestAnimationFrame(() => {
                    if (this.tapeRef.el) {
                        this.tapeRef.el.scrollLeft = scrollPosition.left;
                        this.tapeRef.el.scrollTop = scrollPosition.top;
                    }
                });
            }
        } catch (error) {
            if (
                !this._destroyed &&
                requestSequence === this._requestSequence &&
                error.name !== "ConnectionAbortedError"
            ) {
                if (!this.state.data && this._storedPropertyFallbackPending) {
                    this._storedPropertyFallbackPending = false;
                    this.state.propertyId = null;
                    this.state.filters = cloneEmptyFilters();
                    this.frontdeskState.update({ propertyId: null });
                    return this.loadData({ background, preserveScroll: false });
                }
                const failure = refreshFailureViewState(
                    this.state.data,
                    errorMessage(error, _t("Unable to refresh reservation planning."))
                );
                this.state.error = failure.error;
                this.state.stale = failure.stale;
                if (this.state.data) {
                    this.state.propertyId = asId(this.state.data.meta.property_id);
                    this.state.startDate = this.state.data.meta.start_date;
                    this.state.dayCount = this.state.data.meta.day_count;
                    this.state.filters = normaliseFilters(this._lastSuccessfulFilters);
                    this.frontdeskState.update({
                        propertyId: this.state.propertyId,
                        businessDate:
                            this.state.data.meta.business_date || this.state.startDate,
                    });
                } else {
                    this.state.propertyId = requestedPropertyId;
                    this.state.startDate = requestedStartDate;
                    this.state.dayCount = requestedDayCount;
                    this.state.filters = requestedFilters;
                }
                this.state.ariaStatus = this.state.data
                    ? _t("Refresh failed. Previously loaded planning remains visible.")
                    : this.state.error;
            }
        } finally {
            if (!this._destroyed && requestSequence === this._requestSequence) {
                this.state.loading = false;
                this.state.refreshing = false;
                this._request = null;
            }
        }
    }

    onPropertyChange(event) {
        this.state.propertyId = asId(event.target.value);
        this.state.filters = cloneEmptyFilters();
        this.frontdeskState.update({ propertyId: this.state.propertyId });
        this.loadData({ preserveScroll: false });
    }

    onStartDateChange(event) {
        this.state.startDate = event.target.value || null;
        this.frontdeskState.update({ businessDate: this.state.startDate });
        this.loadData({ preserveScroll: false });
    }

    setDayCount(dayCount) {
        if (this.state.dayCount === dayCount) {
            return;
        }
        this.state.dayCount = dayCount;
        this.loadData({ preserveScroll: false });
    }

    optionValue(option) {
        return option.id ?? option.key ?? option.value;
    }

    optionLabel(option) {
        return option.name || option.label || option.display_name || this.optionValue(option);
    }

    singleFilterValue(name) {
        const value = this.state.filters[name];
        return Array.isArray(value) && value.length ? String(value[0]) : "";
    }

    isFilterOptionSelected(option, name) {
        return String(this.optionValue(option)) === this.singleFilterValue(name);
    }

    onFilterSelect(event, name, numeric = false) {
        const value = event.target.value;
        this.state.filters[name] = value ? [numeric ? Number(value) : value] : [];
    }

    applyFilters() {
        return this.loadData({ preserveScroll: false });
    }

    clearFilters() {
        this.state.filters = cloneEmptyFilters();
        return this.loadData({ preserveScroll: false });
    }

    activeFilterCount() {
        return Object.values(this.state.filters).filter((value) =>
            Array.isArray(value) ? value.length : String(value || "").trim()
        ).length;
    }

    planningStyle() {
        const days = this.state.data?.days.length || this.state.dayCount;
        return `--hotel-days: ${days}; --hotel-timeline-width: ${days * DAY_WIDTH_PX}px; --hotel-total-width: ${ROOM_COLUMN_WIDTH_PX + days * DAY_WIDTH_PX}px;`;
    }

    dayStatus(row, day) {
        return row.dayStatusByIndex[day.index] || {
            index: day.index,
            date: day.date,
            primary_status: "vacant",
            primaryClass: "vacant",
            hk_status: false,
            housekeepingClass: "unknown",
            capacity_blocker: false,
            blockerClass: "unknown",
            alertTypes: [],
            reservation_id: false,
            action: false,
        };
    }

    dayCellClass(row, day) {
        const status = this.dayStatus(row, day);
        return [
            "o_hotel_planning_cell",
            `o_primary_${status.primaryClass}`,
            status.hk_status ? `o_hk_${status.housekeepingClass}` : "",
            status.capacity_blocker ? `o_blocker_${status.blockerClass}` : "",
            status.alertTypes.length ? "o_has_alert" : "",
            !status.action && !status.reservation_action && !status.reservation_id
                ? "o_is_readonly"
                : "",
            day.is_today ? "o_is_today" : "",
            day.is_business_date ? "o_is_business_date" : "",
        ]
            .filter(Boolean)
            .join(" ");
    }

    statusLabel(status) {
        return STATUS_LABELS[status] || String(status || "").replaceAll("_", " ");
    }

    roomAriaLabel(row) {
        return [
            `${_t("Room")} ${row.name}`,
            row.roomTypeName,
            this.statusLabel(row.occupancy_status),
            this.statusLabel(row.hk_status),
            this.statusLabel(row.capacity_blocker),
            ...row.alerts.map((alert) => alert.label),
        ]
            .filter(Boolean)
            .join(", ");
    }

    dayCellAriaLabel(row, day) {
        const status = this.dayStatus(row, day);
        return [
            `${_t("Room")} ${row.name}`,
            formatOperationalDateTime(day.date),
            day.is_today ? _t("Today") : "",
            day.is_business_date ? _t("Business Date") : "",
            this.statusLabel(status.primary_status),
            this.statusLabel(status.hk_status),
            this.statusLabel(status.capacity_blocker),
            ...status.alertTypes.map(
                (alert) => ALERT_LABELS[alert] || this.statusLabel(alert)
            ),
            status.action ? _t("Create a reservation") : "",
        ]
            .filter(Boolean)
            .join(", ");
    }

    onTapeKeydown(event) {
        const tape = this.tapeRef.el;
        const navigationKeys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];
        if (!tape || !navigationKeys.includes(event.key)) {
            return;
        }
        const selector = ".o_hotel_planning_cell, .o_hotel_reservation_bar";
        const rows = [...tape.querySelectorAll(".o_hotel_planning_row")];
        if (!rows.length) {
            return;
        }
        const findInRow = (row, targetDay, excluded = null) => {
            const candidates = [...row.querySelectorAll(selector)].filter(
                (candidate) => candidate !== excluded
            );
            const covering = candidates.filter((candidate) => {
                const start = Number(candidate.dataset.dayIndex);
                const end = Number(candidate.dataset.dayEnd ?? start);
                return targetDay >= start && targetDay <= end;
            });
            return (
                covering.find((candidate) => candidate.classList.contains("o_hotel_reservation_bar")) ||
                covering[0] ||
                candidates.sort(
                    (left, right) =>
                        Math.abs(Number(left.dataset.dayIndex) - targetDay) -
                        Math.abs(Number(right.dataset.dayIndex) - targetDay)
                )[0]
            );
        };
        const current = event.target.closest(selector);
        if (!current) {
            const first = rows.map((row) => findInRow(row, 0)).find(Boolean);
            if (first) {
                event.preventDefault();
                first.focus();
            }
            return;
        }
        const currentRow = current.closest(".o_hotel_planning_row");
        const rowIndex = rows.indexOf(currentRow);
        const startDay = Number(current.dataset.dayIndex);
        const endDay = Number(current.dataset.dayEnd ?? startDay);
        const isRtl = globalThis.getComputedStyle?.(tape).direction === "rtl";
        let target = null;
        if (event.key === "ArrowUp" && rowIndex > 0) {
            target = findInRow(rows[rowIndex - 1], startDay);
        } else if (event.key === "ArrowDown" && rowIndex < rows.length - 1) {
            target = findInRow(rows[rowIndex + 1], startDay);
        } else if (event.key === "Home") {
            target = findInRow(currentRow, 0);
        } else if (event.key === "End") {
            target = findInRow(currentRow, this.state.data.days.length - 1);
        } else if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
            const chronologicalForward = isRtl ? event.key === "ArrowLeft" : event.key === "ArrowRight";
            const targetDay = chronologicalForward ? endDay + 1 : startDay - 1;
            if (targetDay >= 0 && targetDay < this.state.data.days.length) {
                target = findInRow(currentRow, targetDay, current);
            }
        }
        if (target) {
            event.preventDefault();
            target.focus();
        }
    }

    async openAction(action) {
        if (!action) {
            return;
        }
        const propertyId = asId(this.state.data?.meta?.property_id) || this.state.propertyId;
        const businessDate =
            this.state.data?.meta?.business_date || this.state.data?.meta?.start_date || this.state.startDate;
        await this.action.doAction(
            actionWithFrontdeskContext(
                action,
                propertyId,
                businessDate
            )
        );
    }

    openDayCell(row, day) {
        const status = this.dayStatus(row, day);
        if (status.action) {
            return this.openAction(status.action);
        }
        if (status.reservation_action) {
            return this.openAction(status.reservation_action);
        }
        if (status.reservation_id) {
            const reservation = row.reservations.find(
                (item) => Number(item.id) === Number(status.reservation_id)
            );
            if (reservation?.action) {
                return this.openAction(reservation.action);
            }
            return this.openReservation({ id: status.reservation_id });
        }
    }

    openReservation(reservation) {
        return this.openAction(
            reservation.action || {
                type: "ir.actions.act_window",
                name: _t("Reservation"),
                res_model: "hotel.reservation",
                views: [[false, "form"]],
                res_id: reservation.id,
            }
        );
    }

    openRoom(row) {
        return this.openAction({
            type: "ir.actions.act_window",
            name: _t("Room"),
            res_model: "hotel.room",
            views: [[false, "form"]],
            res_id: row.id,
        });
    }

    newReservation() {
        const action = this.state.data?.actions?.new_reservation || {
            type: "ir.actions.act_window",
            name: _t("New Reservation"),
            res_model: "hotel.reservation",
            views: [[false, "form"]],
            target: "current",
            context: {},
        };
        const startDate = this.state.data?.meta?.start_date || this.state.startDate;
        return this.openAction({
            ...action,
            context: {
                default_checkin_date: atNoon(startDate),
                default_checkout_date: atNoon(addIsoDays(startDate, 1)),
                ...(action.context || {}),
            },
        });
    }

    openReservationGantt() {
        return this.openAction(this.state.data?.actions?.reservation_gantt);
    }

    reservationStyle(reservation) {
        return [
            `--reservation-start: ${reservation.gridStart}`,
            `--reservation-span: ${reservation.gridSpan}`,
            `--reservation-lane: ${reservation.lane + 1}`,
        ].join("; ");
    }

    rowTimelineStyle(row) {
        const laneCount = row.laneCount || 1;
        const reservationHeight = laneCount * RESERVATION_LANE_HEIGHT_REM;
        return `--reservation-lanes: ${laneCount}; --reservation-height: ${reservationHeight}rem`;
    }

    reservationDetails(reservation) {
        return [reservation.agency?.name, reservation.group?.name, reservation.bill_to?.name]
            .filter(Boolean)
            .join(" · ");
    }

    reservationAriaLabel(reservation) {
        return [
            reservation.name,
            reservation.guestName,
            reservation.state_label || this.statusLabel(reservation.state),
            `${this.formatDateTime(reservation.start_datetime)} – ${this.formatDateTime(reservation.end_datetime)}`,
            this.reservationDetails(reservation),
            ...reservation.warningLabels,
        ]
            .filter(Boolean)
            .join(", ");
    }

    reservationBalance(reservation) {
        if (!reservation.finance?.has_balance) {
            return "";
        }
        return formatCurrency(reservation.finance.amount_due, {
            ...this.state.data?.meta.currency,
            name: reservation.finance.currency_name || this.state.data?.meta.currency?.name,
        });
    }

    formatDateTime(value) {
        return formatOperationalDateTime(value, this.state.data?.meta?.timezone);
    }

    operationalText(value) {
        return westernDigits(value);
    }

    weekdayLabel(day) {
        return formatWeekday(day.date) || day.weekday;
    }

    formatCount(value) {
        return formatNumber(value, { maximumFractionDigits: 0 });
    }

    updatedAtLabel() {
        return formatUpdatedAt(this.state.updatedAt ? new Date(this.state.updatedAt) : null);
    }
}

registry.category("actions").add("hotel_board.planning", HotelPlanning);
