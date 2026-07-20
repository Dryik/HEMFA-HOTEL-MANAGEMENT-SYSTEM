import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import {
    actionWithFrontdeskContext,
    addIsoDays,
    asArray,
    asId,
    errorMessage,
    formatBusinessDateParts,
    formatCurrency,
    formatNumber,
    formatOperationalDateTime,
    refreshFailureViewState,
    westernDigits,
} from "../shared/frontdesk_utils";
import "../shared/frontdesk_state_service";

const REFRESH_INTERVAL_MS = 30_000;
const STALE_AFTER_MS = REFRESH_INTERVAL_MS * 2;
const SEARCH_DEBOUNCE_MS = 300;
const ACTIVITY_LIMIT = 50;
const ACTIVITY_KEYS = [
    "arrivals",
    "departures",
    "in_house",
    "stayovers",
    "bookings",
    "cancellations",
    "overbookings",
];

function normaliseActivity(activity = {}) {
    return {
        key: activity.key || "arrivals",
        label: activity.label || _t("Arrivals"),
        includeCompleted: Boolean(activity.include_completed),
        supportsCompleted: Boolean(activity.supports_completed),
        total: Number(activity.total || 0),
        pendingTotal: Number(activity.pending_total || 0),
        truncated: Boolean(activity.truncated),
        rows: asArray(activity.rows),
        listAction: activity.list_action || false,
    };
}

function normaliseSnapshot(raw = {}) {
    return {
        version: raw.version || 0,
        meta: raw.meta || {},
        permissions: raw.permissions || {},
        occupancy: {
            percentage: Number(raw.occupancy?.percentage || 0),
            availableUnits: Number(raw.occupancy?.available_units || 0),
            bookedUnits: Number(raw.occupancy?.booked_units || 0),
            outOfService: Number(raw.occupancy?.out_of_service || 0),
            houseUse: Number(raw.occupancy?.house_use || 0),
        },
        tabs: asArray(raw.tabs).map((tab) => ({
            key: tab.key,
            label: tab.label,
            count: Number(tab.count || 0),
            pendingCount: Number(tab.pending_count || 0),
        })),
        activity: normaliseActivity(raw.activity),
        operationalKpis: asArray(raw.operational_kpis),
        actions: raw.actions || {},
    };
}

export class HotelDashboard extends Component {
    static template = "hotel_board.HotelDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.frontdeskState = useService("hotel_frontdesk_state");
        const stored = this.frontdeskState.get();
        const actionContext = this.props.action?.context || {};
        this.state = useState({
            data: null,
            activity: null,
            // Bumped on user-driven activity reloads (tab, toggle, search,
            // date); re-keys the rows so the list plays its entrance fade.
            // Background polls keep the keys and patch rows in place.
            activityGeneration: 0,
            activeTab: "arrivals",
            includeCompleted: false,
            query: "",
            searchOpen: false,
            menuOpen: false,
            drawerRow: null,
            loading: true,
            activityLoading: false,
            refreshing: false,
            error: null,
            stale: false,
            updatedAt: null,
            ariaStatus: _t("Loading the Front Desk dashboard."),
            businessDate:
                actionContext.default_business_date ||
                actionContext.business_date ||
                stored.businessDate,
            busyRows: {},
        });
        this._snapshotSequence = 0;
        this._activitySequence = 0;
        this._refreshTimer = null;
        this._searchTimer = null;
        this._lastAttemptAt = 0;
        this._destroyed = false;
        this._onVisibilityChange = () => this.onVisibilityChange();
        this._onKeydown = (event) => this.onDocumentKeydown(event);

        onMounted(() => {
            this.refreshDashboard();
            this.startRefreshTimer();
            globalThis.document?.addEventListener("visibilitychange", this._onVisibilityChange);
            globalThis.document?.addEventListener("keydown", this._onKeydown);
        });
        onWillUnmount(() => {
            this._destroyed = true;
            this.stopRefreshTimer();
            if (this._searchTimer) {
                browser.clearTimeout(this._searchTimer);
            }
            globalThis.document?.removeEventListener("visibilitychange", this._onVisibilityChange);
            globalThis.document?.removeEventListener("keydown", this._onKeydown);
        });
    }

    startRefreshTimer() {
        if (!this._refreshTimer) {
            this._refreshTimer = browser.setInterval(() => {
                if (!globalThis.document?.hidden) {
                    this.refreshDashboard({ background: true });
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
            this.refreshDashboard({ background: true });
        }
    }

    async refreshDashboard({ background = false } = {}) {
        const sequence = ++this._snapshotSequence;
        const requestedDate = this.state.businessDate;
        this._lastAttemptAt = Date.now();
        this.state.loading = !this.state.data;
        this.state.refreshing = Boolean(this.state.data);
        if (!background) {
            this.state.ariaStatus = _t("Refreshing the Front Desk dashboard.");
        }
        try {
            const raw = await this.orm.silent.call(
                "hotel.frontdesk.workspace",
                "get_dashboard_snapshot",
                [false, requestedDate || false]
            );
            if (this._destroyed || sequence !== this._snapshotSequence) {
                return;
            }
            const data = normaliseSnapshot(raw);
            this.state.data = data;
            this.state.businessDate = data.meta.business_date;
            this.frontdeskState.update({ businessDate: this.state.businessDate });
            this.state.error = null;
            this.state.stale = false;
            this.state.updatedAt = Date.now();

            const canUseInitialActivity =
                this.state.activeTab === "arrivals" &&
                !this.state.includeCompleted &&
                !this.state.query;
            if (canUseInitialActivity) {
                this.state.activity = data.activity;
                if (!background) {
                    this.state.activityGeneration++;
                }
            } else {
                await this.loadActivity({ background });
            }
            this.state.ariaStatus = _t("Front Desk dashboard updated.");
        } catch (error) {
            if (!this._destroyed && sequence === this._snapshotSequence) {
                const failure = refreshFailureViewState(
                    this.state.data,
                    errorMessage(error, _t("Unable to refresh the Front Desk dashboard."))
                );
                this.state.error = failure.error;
                this.state.stale = failure.stale;
                this.state.ariaStatus = this.state.data
                    ? _t("Refresh failed. Previously loaded data remains visible.")
                    : this.state.error;
            }
        } finally {
            if (!this._destroyed && sequence === this._snapshotSequence) {
                this.state.loading = false;
                this.state.refreshing = false;
            }
        }
    }

    async loadActivity({ background = false } = {}) {
        if (!this.state.data) {
            return;
        }
        const sequence = ++this._activitySequence;
        const requestedDate = this.state.businessDate;
        const requestedTab = this.state.activeTab;
        const requestedCompleted = this.state.includeCompleted;
        const requestedQuery = this.state.query;
        if (!background) {
            this.state.activityLoading = true;
            this.state.ariaStatus = _t("Loading dashboard activity.");
        }
        try {
            const raw = await this.orm.silent.call(
                "hotel.frontdesk.workspace",
                "get_dashboard_activity",
                [
                    false,
                    requestedDate,
                    requestedTab,
                    requestedCompleted,
                    requestedQuery || false,
                    ACTIVITY_LIMIT,
                ]
            );
            if (
                this._destroyed ||
                sequence !== this._activitySequence ||
                requestedDate !== this.state.businessDate ||
                requestedTab !== this.state.activeTab
            ) {
                return;
            }
            this.state.activity = normaliseActivity(raw);
            if (!background) {
                this.state.activityGeneration++;
            }
            this.state.data.actions.open_list = raw.list_action;
            this.state.ariaStatus = _t("Dashboard activity updated.");
        } catch (error) {
            if (!this._destroyed && sequence === this._activitySequence) {
                this.notification.add(
                    errorMessage(error, _t("Unable to load dashboard activity.")),
                    { type: "danger" }
                );
                this.state.ariaStatus = _t("Unable to load dashboard activity.");
            }
        } finally {
            if (!this._destroyed && sequence === this._activitySequence) {
                this.state.activityLoading = false;
            }
        }
    }

    changeDate(dayOffset) {
        const nextDate = addIsoDays(this.state.businessDate, dayOffset);
        if (!nextDate || nextDate === this.state.businessDate) {
            return;
        }
        this.closeQuickView();
        this.state.businessDate = nextDate;
        this.frontdeskState.update({ businessDate: nextDate });
        this.refreshDashboard();
    }

    goToday() {
        const today = this.state.data?.meta?.current_business_date;
        if (!today || today === this.state.businessDate) {
            return;
        }
        this.closeQuickView();
        this.state.businessDate = today;
        this.frontdeskState.update({ businessDate: today });
        this.refreshDashboard();
    }

    selectActivity(key) {
        if (!ACTIVITY_KEYS.includes(key) || key === this.state.activeTab) {
            return;
        }
        this.closeQuickView();
        this.state.activeTab = key;
        this.state.includeCompleted = false;
        this.loadActivity();
    }

    onTabKeydown(event, key) {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            return;
        }
        event.preventDefault();
        let nextIndex;
        if (event.key === "Home") {
            nextIndex = 0;
        } else if (event.key === "End") {
            nextIndex = ACTIVITY_KEYS.length - 1;
        } else {
            const direction = globalThis.document?.documentElement?.dir === "rtl" ? -1 : 1;
            const delta = event.key === "ArrowRight" ? direction : -direction;
            nextIndex = (ACTIVITY_KEYS.indexOf(key) + delta + ACTIVITY_KEYS.length) % ACTIVITY_KEYS.length;
        }
        const nextKey = ACTIVITY_KEYS[nextIndex];
        this.selectActivity(nextKey);
        browser.requestAnimationFrame(() => {
            globalThis.document
                ?.querySelector(`[data-dashboard-activity="${nextKey}"]`)
                ?.focus();
        });
    }

    toggleCompleted(event) {
        this.state.includeCompleted = Boolean(event.target.checked);
        this.loadActivity();
    }

    toggleSearch() {
        this.state.searchOpen = !this.state.searchOpen;
        if (!this.state.searchOpen && this.state.query) {
            this.state.query = "";
            this.loadActivity();
        } else if (this.state.searchOpen) {
            browser.requestAnimationFrame(() => {
                globalThis.document?.querySelector("#hotel-dashboard-search")?.focus();
            });
        }
    }

    onSearchInput(event) {
        this.state.query = event.target.value;
        if (this._searchTimer) {
            browser.clearTimeout(this._searchTimer);
        }
        this._searchTimer = browser.setTimeout(() => {
            this._searchTimer = null;
            this.loadActivity();
        }, SEARCH_DEBOUNCE_MS);
    }

    toggleMenu() {
        this.state.menuOpen = !this.state.menuOpen;
    }

    async openAction(action) {
        if (!action) {
            return;
        }
        this.state.menuOpen = false;
        const propertyId = asId(this.state.data?.meta?.property_id);
        await this.action.doAction(
            actionWithFrontdeskContext(action, propertyId, this.state.businessDate)
        );
    }

    newReservation() {
        return this.openAction(this.state.data?.actions?.new_reservation);
    }

    openPlanning() {
        return this.openAction(this.state.data?.actions?.planning);
    }

    openOperationalKpi(kpi) {
        return this.openAction(kpi?.action);
    }

    openFullList() {
        return this.openAction(this.state.activity?.listAction || this.state.data?.actions?.open_list);
    }

    openRowAction(row, key) {
        return this.openAction(row.actions?.[key]);
    }

    openQuickView(row) {
        this.state.menuOpen = false;
        this._drawerReturnFocus = globalThis.document?.activeElement || null;
        this.state.drawerRow = row;
        browser.requestAnimationFrame(() => {
            globalThis.document?.querySelector(".o_hotel_drawer_close")?.focus();
        });
    }

    closeQuickView(options = {}) {
        const restoreFocus = options?.restoreFocus !== false;
        this.state.drawerRow = null;
        if (restoreFocus && this._drawerReturnFocus?.focus) {
            browser.requestAnimationFrame(() => this._drawerReturnFocus?.focus());
        }
        this._drawerReturnFocus = null;
    }

    onDrawerBackdropClick(event) {
        if (event.target === event.currentTarget) {
            this.closeQuickView();
        }
    }

    onDocumentKeydown(event) {
        if (!this.state.drawerRow) {
            return;
        }
        if (event.key === "Escape") {
            event.preventDefault();
            this.closeQuickView();
            return;
        }
        if (event.key !== "Tab") {
            return;
        }
        const drawer = globalThis.document?.querySelector(".o_hotel_dashboard_drawer");
        const focusable = Array.from(
            drawer?.querySelectorAll(
                'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            ) || []
        );
        if (!focusable.length) {
            return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && globalThis.document?.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && globalThis.document?.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }

    openDrawerAction(key) {
        const row = this.state.drawerRow;
        this.closeQuickView({ restoreFocus: false });
        return this.openRowAction(row, key);
    }

    guestInitials(row) {
        const name = String(row?.guest?.name || "").trim();
        if (!name) {
            return "—";
        }
        return name
            .split(/\s+/)
            .slice(0, 2)
            .map((part) => part.charAt(0))
            .join("")
            .toUpperCase();
    }

    async runPrimaryAction(row) {
        const key = row.primary_action?.key;
        if (key === "open") {
            return this.openRowAction(row, "reservation");
        }
        const method = key === "check_in" ? "action_check_in" : key === "check_out" ? "action_check_out" : null;
        if (!method || this.state.busyRows[row.id]) {
            return;
        }
        if (key === "check_out") {
            const confirmed = await new Promise((resolve) => {
                this.dialog.add(ConfirmationDialog, {
                    title: _t("Check out"),
                    body: _t(
                        "Check out %(guest)s from room %(room)s? Checkout ends the stay and cannot be undone.",
                        { guest: row.guest?.name || "", room: row.room?.name || "—" }
                    ),
                    confirmLabel: _t("Check Out"),
                    cancelLabel: _t("Keep Stay"),
                    confirm: () => resolve(true),
                    cancel: () => resolve(false),
                });
            });
            if (!confirmed) {
                return;
            }
        }
        this.state.busyRows[row.id] = true;
        try {
            await this.orm.call("hotel.reservation", method, [[row.id]]);
            this.notification.add(
                key === "check_in" ? _t("Guest checked in.") : _t("Guest checked out."),
                { type: "success" }
            );
            await this.refreshDashboard({ background: true });
        } catch (error) {
            this.notification.add(errorMessage(error, _t("Unable to complete the workflow.")), {
                type: "danger",
            });
            this.state.ariaStatus = _t("Unable to complete the workflow.");
        } finally {
            delete this.state.busyRows[row.id];
        }
    }

    isRowBusy(row) {
        return Boolean(this.state.busyRows[row.id]);
    }

    selectedDateParts() {
        return formatBusinessDateParts(this.state.businessDate);
    }

    formatDateTime(value) {
        return formatOperationalDateTime(value, this.state.data?.meta?.timezone);
    }

    formatCount(value) {
        return formatNumber(value, { maximumFractionDigits: 0 });
    }

    formatPercentage(value) {
        return `${formatNumber(value, { maximumFractionDigits: 1 })}%`;
    }

    formatAmount(value) {
        return formatCurrency(value, this.state.data?.meta?.currency);
    }

    occupancyAriaLabel() {
        return `${this.formatPercentage(this.state.data?.occupancy?.percentage || 0)} ${_t(
            "occupancy"
        )}`;
    }

    operationalText(value) {
        return westernDigits(value);
    }

    minorGuests(row) {
        return Number(row.teenagers || 0) + Number(row.children || 0) + Number(row.infants || 0);
    }

    nightsAriaLabel(row) {
        return `${this.formatCount(row.nights)} ${_t("nights")}`;
    }

    adultsAriaLabel(row) {
        return `${this.formatCount(row.adults)} ${_t("adults")}`;
    }

    childrenAriaLabel(row) {
        return `${this.formatCount(this.minorGuests(row))} ${_t("children")}`;
    }

    activityCountLabel() {
        const labels = {
            arrivals: _t("Arriving guests"),
            departures: _t("Departing guests"),
            in_house: _t("In-house guests"),
            stayovers: _t("Stayovers"),
            bookings: _t("Bookings"),
            cancellations: _t("Cancellations"),
            overbookings: _t("Overbookings"),
        };
        return labels[this.state.activeTab] || _t("Activity records");
    }

    completedLabel() {
        return this.state.activeTab === "departures"
            ? _t("Show checked-out guests")
            : _t("Show completed arrivals");
    }
}

registry.category("actions").add("hotel_board.dashboard", HotelDashboard);
