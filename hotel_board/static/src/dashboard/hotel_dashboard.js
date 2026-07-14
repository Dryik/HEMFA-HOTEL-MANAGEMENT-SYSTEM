import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
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
    refreshFailureViewState,
    westernDigits,
} from "../shared/frontdesk_utils";
import "../shared/frontdesk_state_service";

const REFRESH_INTERVAL_MS = 60_000;
const STALE_AFTER_MS = REFRESH_INTERVAL_MS * 2;

const KPI_ORDER = [
    "arrivals",
    "departures",
    "in_house",
    "reserved",
    "vacant_clean",
    "vacant_dirty",
    "out_of_order",
    "house_use",
    "occupancy",
    "adr",
    "revpar",
];

const KPI_DEFAULTS = {
    arrivals: { label: _t("Arrivals"), tone: "warning" },
    departures: { label: _t("Departures"), tone: "info" },
    in_house: { label: _t("In House"), tone: "success" },
    reserved: { label: _t("Reserved Rooms"), tone: "primary" },
    vacant_clean: { label: _t("Vacant Clean"), tone: "success" },
    vacant_dirty: { label: _t("Vacant Dirty"), tone: "danger" },
    out_of_order: { label: _t("Out of Order"), tone: "neutral" },
    house_use: { label: _t("House Use"), tone: "neutral" },
    occupancy: { label: _t("Occupancy"), tone: "brand" },
    adr: { label: _t("ADR"), tone: "brand" },
    revpar: { label: _t("RevPAR"), tone: "brand" },
};

function cssToken(value, fallback = "unknown") {
    const token = String(value || "").toLowerCase().replace(/[^a-z0-9_-]/g, "_");
    return token || fallback;
}

function normaliseMetric(key, metric, raw, actions) {
    const fallback = KPI_DEFAULTS[key] || { label: key, tone: "neutral" };
    const legacyKeys = {
        arrivals: "arrivals_today",
        departures: "departures_today",
        house_use: "admin_use",
        occupancy: "occupancy_pct",
    };
    const legacyValue = raw[legacyKeys[key] || key];
    if (metric === undefined && legacyValue === undefined) {
        return null;
    }
    const value = metric && typeof metric === "object" ? metric : { value: metric ?? legacyValue };
    return {
        key,
        label: value.label || fallback.label,
        value: value.value ?? legacyValue,
        format:
            value.format || (key === "occupancy" ? "percent" : ["adr", "revpar"].includes(key) ? "currency" : "integer"),
        available: value.available !== false && value.value !== null,
        mode: value.mode || false,
        modeLabel: value.mode_label || false,
        tone: value.tone || fallback.tone,
        action: value.action || actions?.[key] || false,
    };
}

function normaliseRoom(room, floor) {
    let primaryStatus = room.primary_status || room.occupancy_status || room.status || "vacant";
    let capacityBlocker = room.capacity_blocker || false;
    let housekeepingStatus = room.hk_status || room.housekeeping_status || false;
    if (primaryStatus === "out_of_order") {
        capacityBlocker = "out_of_order";
        primaryStatus = room.occupancy_status || "vacant";
    } else if (["house_use", "admin_use"].includes(primaryStatus)) {
        capacityBlocker = "house_use";
        primaryStatus = room.occupancy_status || "vacant";
    } else if (primaryStatus === "dirty") {
        housekeepingStatus = "dirty";
        primaryStatus = room.occupancy_status || "vacant";
    }
    const reservation = room.reservation || (room.reservation_id
        ? {
              id: room.reservation_id,
              name: room.reservation_name,
              guest_name: room.guest_name,
              arrival: room.arrival,
              departure: room.departure,
          }
        : false);
    return {
        ...room,
        id: room.id || room.room_id,
        name: room.name || room.room_name,
        floorId: asId(room.floor_id) || floor.id,
        floorName: room.floor_name || floor.name,
        roomTypeName: room.room_type?.name || room.room_type || "",
        primaryStatus,
        primaryClass: cssToken(primaryStatus),
        primaryLabel: room.primary_label || KPI_DEFAULTS[primaryStatus]?.label || primaryStatus,
        housekeepingStatus,
        housekeepingClass: cssToken(housekeepingStatus),
        housekeepingLabel: room.hk_label || housekeepingStatus || "",
        capacityBlocker,
        blockerClass: cssToken(capacityBlocker),
        reservation,
        alerts: asArray(room.alerts).map((alert) => ({
            ...alert,
            typeClass: cssToken(alert.type),
            severityClass: cssToken(alert.severity, "info"),
        })),
        action: room.action || false,
    };
}

function normaliseSnapshot(raw = {}) {
    const meta = raw.meta || {
        property_id: raw.property_id,
        property_name: raw.property_name,
        business_date: raw.business_date,
        metric_mode: "forecast",
        metric_label: _t("Forecast"),
        currency: {},
    };
    const metrics = raw.kpis || {};
    const kpis = KPI_ORDER.map((key) => normaliseMetric(key, metrics[key], raw, raw.actions)).filter(Boolean);
    let floors = asArray(raw.floors);
    if (!floors.length && asArray(raw.room_board).length) {
        const byFloor = new Map();
        for (const room of raw.room_board) {
            const name = room.floor_name || _t("Unassigned Floor");
            if (!byFloor.has(name)) {
                byFloor.set(name, { id: name, name, sequence: byFloor.size, rooms: [] });
            }
            byFloor.get(name).rooms.push(room);
        }
        floors = [...byFloor.values()];
    }
    floors = floors.map((floor, index) => ({
        ...floor,
        id: floor.id ?? `floor-${index}`,
        name: floor.name || _t("Unassigned Floor"),
        rooms: asArray(floor.rooms).map((room) => normaliseRoom(room, floor)),
    }));
    const attention = raw.attention || { total: 0, items: [] };
    return {
        version: raw.version || 0,
        meta,
        permissions: raw.permissions || {},
        kpis,
        attention: {
            total: Number(attention.total || 0),
            items: asArray(attention.items).map((item) => ({
                ...item,
                severityClass: cssToken(item.severity, "info"),
            })),
        },
        floors,
        legend: raw.legend || {},
        actions: raw.actions || {},
    };
}

export class HotelDashboard extends Component {
    static template = "hotel_board.HotelDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.frontdeskState = useService("hotel_frontdesk_state");
        const stored = this.frontdeskState.get();
        const actionContext = this.props.action?.context || {};
        this.state = useState({
            data: null,
            loading: true,
            refreshing: false,
            error: null,
            stale: false,
            updatedAt: null,
            ariaStatus: _t("Loading the Front Desk workspace."),
            propertyId: null,
            businessDate:
                actionContext.default_business_date ||
                actionContext.business_date ||
                stored.businessDate,
            collapsedFloors: {},
        });
        this._request = null;
        this._requestSequence = 0;
        this._refreshTimer = null;
        this._lastAttemptAt = 0;
        this._destroyed = false;
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
                    this.loadData({ background: true });
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
            if (this.state.updatedAt && Date.now() - this.state.updatedAt >= STALE_AFTER_MS) {
                this.state.stale = true;
            }
            this.loadData({ background: true });
        }
    }

    async loadData({ background = false } = {}) {
        this._request?.abort?.(false);
        const requestSequence = ++this._requestSequence;
        const requestedPropertyId = this.state.propertyId;
        const requestedBusinessDate = this.state.businessDate;
        this._lastAttemptAt = Date.now();
        this.state.loading = !this.state.data;
        this.state.refreshing = Boolean(this.state.data);
        if (!background) {
            this.state.ariaStatus = _t("Refreshing the Front Desk workspace.");
        }
        try {
            this._request = this.orm.silent.call("hotel.frontdesk.workspace", "get_workspace_snapshot", [
                false,
                this.state.businessDate || false,
            ]);
            const raw = await this._request;
            if (this._destroyed || requestSequence !== this._requestSequence) {
                return;
            }
            const data = normaliseSnapshot(raw);
            this.state.data = data;
            this.state.propertyId = asId(data.meta.property_id);
            this.state.businessDate = data.meta.business_date;
            this.frontdeskState.update({
                businessDate: this.state.businessDate,
            });
            for (const floor of data.floors) {
                if (!(floor.id in this.state.collapsedFloors)) {
                    this.state.collapsedFloors[floor.id] = Boolean(floor.collapsed_default);
                }
            }
            this.state.error = null;
            this.state.stale = false;
            this.state.updatedAt = Date.now();
            this.state.ariaStatus = _t("Front Desk data updated.");
        } catch (error) {
            if (
                !this._destroyed &&
                requestSequence === this._requestSequence &&
                error.name !== "ConnectionAbortedError"
            ) {
                const failure = refreshFailureViewState(
                    this.state.data,
                    errorMessage(error, _t("Unable to refresh the Front Desk workspace."))
                );
                this.state.error = failure.error;
                this.state.stale = failure.stale;
                if (this.state.data) {
                    this.state.propertyId = asId(this.state.data.meta.property_id);
                    this.state.businessDate = this.state.data.meta.business_date;
                    this.frontdeskState.update({
                        businessDate: this.state.businessDate,
                    });
                } else {
                    this.state.propertyId = requestedPropertyId;
                    this.state.businessDate = requestedBusinessDate;
                }
                this.state.ariaStatus = this.state.data
                    ? _t("Refresh failed. Previously loaded data remains visible.")
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

    onDateChange(event) {
        this.state.businessDate = event.target.value || null;
        this.frontdeskState.update({ businessDate: this.state.businessDate });
        this.loadData();
    }

    toggleFloor(floorId) {
        this.state.collapsedFloors[floorId] = !this.state.collapsedFloors[floorId];
    }

    isFloorCollapsed(floorId) {
        return Boolean(this.state.collapsedFloors[floorId]);
    }

    async openAction(action) {
        if (!action) {
            return;
        }
        const propertyId = asId(this.state.data?.meta?.property_id) || this.state.propertyId;
        const businessDate = this.state.data?.meta?.business_date || this.state.businessDate;
        await this.action.doAction(
            actionWithFrontdeskContext(action, propertyId, businessDate)
        );
    }

    openMetric(metric) {
        return this.openAction(metric.action);
    }

    openAttention(item) {
        return this.openAction(item.action);
    }

    openBoardItem(room) {
        if (room.action) {
            return this.openAction(room.action);
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: room.reservation ? _t("Reservation") : _t("Room"),
            res_model: room.reservation ? "hotel.reservation" : "hotel.room",
            views: [[false, "form"]],
            res_id: room.reservation?.id || room.id,
            context: {
                default_property_id:
                    asId(this.state.data?.meta?.property_id) || this.state.propertyId,
                default_business_date:
                    this.state.data?.meta?.business_date || this.state.businessDate,
            },
        });
    }

    newReservation() {
        const checkinDate = this.state.data?.meta?.business_date || this.state.businessDate;
        const fallback = {
            type: "ir.actions.act_window",
            name: _t("New Reservation"),
            res_model: "hotel.reservation",
            views: [[false, "form"]],
            target: "current",
            context: {},
        };
        const action = this.state.data?.actions?.new_reservation || fallback;
        return this.openAction({
            ...action,
            context: {
                default_checkin_date: atNoon(checkinDate),
                default_checkout_date: atNoon(addIsoDays(checkinDate, 1)),
                ...(action.context || {}),
            },
        });
    }

    openPlanning() {
        const action = this.state.data?.actions?.planning || {
            type: "ir.actions.client",
            tag: "hotel_board.planning",
            name: _t("Planning"),
            context: {},
        };
        return this.openAction(action);
    }

    formatMetric(metric) {
        if (!metric.available) {
            return "—";
        }
        if (metric.format === "percent") {
            return `${formatNumber(metric.value, { maximumFractionDigits: 1 })}%`;
        }
        if (metric.format === "currency") {
            return formatCurrency(metric.value, this.state.data?.meta?.currency);
        }
        return formatNumber(metric.value, { maximumFractionDigits: 0 });
    }

    metricMode(metric) {
        if (!metric.available) {
            return _t("Unavailable");
        }
        if (metric.modeLabel) {
            return metric.modeLabel;
        }
        if (metric.mode === "forecast") {
            return _t("Forecast");
        }
        if (metric.mode === "actual") {
            return _t("Actual");
        }
        return "";
    }

    metricAriaLabel(metric) {
        return `${metric.label}: ${this.formatMetric(metric)}${this.metricMode(metric) ? `, ${this.metricMode(metric)}` : ""}`;
    }

    roomAriaLabel(room) {
        if (room.aria_label) {
            return [
                room.aria_label,
                room.reservation?.name,
                room.reservation?.arrival
                    ? `${_t("Arrival")}: ${this.formatDateTime(room.reservation.arrival)}`
                    : "",
                room.reservation?.departure
                    ? `${_t("Departure")}: ${this.formatDateTime(room.reservation.departure)}`
                    : "",
                ...room.alerts.map((alert) => alert.label),
            ]
                .filter(Boolean)
                .join(", ");
        }
        return [
            `${_t("Room")} ${room.name}`,
            room.primaryLabel,
            room.housekeepingLabel,
            room.capacityBlocker ? room.capacityBlocker.replaceAll("_", " ") : "",
            room.reservation?.guest_name,
            ...room.alerts.map((alert) => alert.label),
        ]
            .filter(Boolean)
            .join(", ");
    }

    formatDateTime(value) {
        return formatOperationalDateTime(value, this.state.data?.meta?.timezone);
    }

    operationalText(value) {
        return westernDigits(value);
    }

    updatedAtLabel() {
        return formatUpdatedAt(this.state.updatedAt ? new Date(this.state.updatedAt) : null);
    }
}

registry.category("actions").add("hotel_board.dashboard", HotelDashboard);
