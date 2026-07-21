import { after, describe, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame, Deferred } from "@odoo/hoot-mock";
import {
    contains,
    mockService,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";

import { HotelDashboard } from "@hotel_board/dashboard/hotel_dashboard";
import { HotelPlanning } from "@hotel_board/planning/hotel_planning";

describe.current.tags("desktop");

const PROPERTY_ID = 2;
const BUSINESS_DATE = "2026-07-13";

function mockFrontdeskState(initial = {}) {
    let state = {
        businessDate: initial.businessDate || null,
    };
    mockService("hotel_frontdesk_state", () => ({
        get() {
            return { ...state };
        },
        update(values = {}) {
            state = { ...state, ...values };
            return { ...state };
        },
    }));
    return () => ({ ...state });
}

function mockAction(callback = () => {}) {
    mockService("action", () => ({
        async doAction(action) {
            callback(action);
            return true;
        },
    }));
}

function dashboardSnapshot(businessDate = BUSINESS_DATE) {
    return {
        version: 3,
        meta: {
            property_id: PROPERTY_ID,
            property_name: "Tripoli Hotel",
            business_date: businessDate,
            current_business_date: BUSINESS_DATE,
            timezone: "Africa/Tripoli",
            currency: {
                name: "LYD",
                symbol: "LYD",
                position: "after",
                decimal_places: 3,
            },
        },
        occupancy: {
            percentage: 50,
            available_units: 20,
            booked_units: 10,
            out_of_service: 1,
            house_use: 0,
        },
        tabs: [
            { key: "arrivals", label: "Arrivals", count: 1, pending_count: 1 },
            { key: "departures", label: "Departures", count: 0, pending_count: 0 },
            { key: "in_house", label: "In-house", count: 10, pending_count: 10 },
            { key: "stayovers", label: "Stayovers", count: 3, pending_count: 3 },
            { key: "bookings", label: "Bookings", count: 0, pending_count: 0 },
            { key: "cancellations", label: "Cancellations", count: 0, pending_count: 0 },
            { key: "overbookings", label: "Overbookings", count: 0, pending_count: 0 },
        ],
        activity: {
            key: "arrivals",
            label: "Arrivals",
            include_completed: false,
            supports_completed: true,
            total: 1,
            pending_total: 1,
            truncated: false,
            rows: [
                    {
                        id: 72,
                        reference: "RES-00072",
                        guest: { id: 7, name: "Ahmed Al-Mansouri" },
                        room: { id: 105, name: "105" },
                        room_type: { id: 10, name: "Double Suite" },
                        housekeeping_status: "clean",
                        checkin: "2026-07-13 12:00:00",
                        checkout: "2026-07-16 12:00:00",
                        nights: 3,
                        adults: 2,
                        teenagers: 0,
                        children: 0,
                        infants: 0,
                        state: "confirmed",
                        state_label: "Confirmed",
                        has_notes: false,
                        finance: false,
                        primary_action: { key: "check_in", label: "Check-in" },
                        actions: {
                            reservation: {
                                type: "ir.actions.act_window",
                                res_model: "hotel.reservation",
                                res_id: 72,
                                context: {
                                    hotel_property_id: 99,
                                    business_date: "2020-01-01",
                                },
                            },
                            guest: {
                                type: "ir.actions.act_window",
                                res_model: "res.partner",
                                res_id: 7,
                            },
                            folio: false,
                            amendment: {
                                type: "ir.actions.act_window",
                                res_model: "hotel.reservation.amendment",
                                views: [[false, "form"]],
                                context: { default_reservation_id: 72 },
                            },
                        },
                    },
            ],
            list_action: {
                type: "ir.actions.act_window",
                res_model: "hotel.reservation",
                domain: [["id", "in", [72]]],
                context: {},
            },
        },
        operational_kpis: [
            {
                key: "booking_requests",
                label: "Booking Requests",
                count: 2,
                action: {
                    type: "ir.actions.act_window",
                    res_model: "hotel.online.booking",
                    domain: [["state", "=", "pending_review"]],
                },
            },
        ],
        actions: {
            open_list: {
                type: "ir.actions.act_window",
                res_model: "hotel.reservation",
                domain: [["id", "in", [72]]],
                context: {},
            },
            new_reservation: {
                type: "ir.actions.act_window",
                res_model: "hotel.reservation",
                views: [[false, "form"]],
                context: {},
            },
            planning: {
                type: "ir.actions.client",
                tag: "hotel_board.planning",
                context: {},
            },
        },
    };
}

function departureActivity() {
    return {
        key: "departures",
        label: "Departures",
        include_completed: false,
        supports_completed: true,
        total: 0,
        pending_total: 0,
        truncated: false,
        rows: [],
        list_action: {
            type: "ir.actions.act_window",
            res_model: "hotel.reservation",
            domain: [["id", "in", []]],
            context: {},
        },
    };
}

function planningWindow() {
    return {
        version: 2,
        meta: {
            property_id: PROPERTY_ID,
            property_name: "Tripoli Hotel",
            business_date: BUSINESS_DATE,
            start_date: BUSINESS_DATE,
            day_count: 7,
            timezone: "Africa/Tripoli",
            currency: { name: "LYD", symbol: "LYD", position: "after" },
        },
        properties: [{ id: PROPERTY_ID, name: "Tripoli Hotel" }],
        days: [
            {
                index: 0,
                date: BUSINESS_DATE,
                label: "13/07/2026",
                weekday: "Mon",
                is_today: true,
                is_business_date: true,
            },
            {
                index: 1,
                date: "2026-07-14",
                label: "14/07/2026",
                weekday: "Tue",
                is_today: false,
                is_business_date: false,
            },
        ],
        filters: {
            applied: {},
            options: { floors: [{ id: 1, name: "First Floor" }] },
        },
        legend: { reservation_states: [], primary: [], housekeeping: [], alerts: [] },
        floors: [
            {
                id: 1,
                name: "First Floor",
                rows: [
                    {
                        id: 101,
                        name: "101",
                        room_type: { id: 10, name: "King" },
                        occupancy_status: "vacant",
                        hk_status: "clean",
                        alerts: [],
                        day_statuses: [
                            {
                                index: 0,
                                date: BUSINESS_DATE,
                                primary_status: "vacant",
                                hk_status: "clean",
                                alert_types: [],
                                can_create: false,
                            },
                            {
                                index: 1,
                                date: "2026-07-14",
                                primary_status: "vacant",
                                hk_status: "clean",
                                alert_types: [],
                                can_create: false,
                            },
                        ],
                        reservations: [],
                    },
                ],
            },
        ],
        totals: { rooms: 1, reservations: 0 },
        actions: {},
    };
}

test("Dashboard renders the compact activity workspace and preserves action context", async () => {
    const response = new Deferred();
    const getFrontdeskState = mockFrontdeskState();
    let openedAction;
    mockAction((action) => {
        openedAction = action;
    });
    onRpc(
        "hotel.frontdesk.workspace",
        "get_dashboard_snapshot",
        ({ args }) => {
            expect(args).toEqual([false, BUSINESS_DATE]);
            return response;
        }
    );
    let activityArgs;
    onRpc("hotel.frontdesk.workspace", "get_dashboard_activity", ({ args }) => {
        activityArgs = args;
        return departureActivity();
    });

    await mountWithCleanup(HotelDashboard, {
        props: {
            action: {
                context: {
                    default_property_id: PROPERTY_ID,
                    default_business_date: BUSINESS_DATE,
                },
            },
        },
    });
    expect(".o_hotel_dashboard_loading").toHaveCount(1);

    response.resolve(dashboardSnapshot());
    await animationFrame();
    expect(".o_hotel_dashboard_loading").toHaveCount(0);
    expect(".o_hotel_activity_row").toHaveText(/Ahmed Al-Mansouri/);
    expect(".o_hotel_occupancy_ring").toHaveText(/50%/);
    expect(".o_hotel_attention_item").toHaveText(/Booking Requests/);
    expect(".o_hotel_room_card").toHaveCount(0);
    expect(getFrontdeskState()).toEqual({
        businessDate: BUSINESS_DATE,
    });

    await contains(".o_hotel_text_action").click();
    expect(".o_hotel_dashboard_drawer").toHaveCount(1);
    expect(".o_hotel_dashboard_drawer").toHaveText(/Ahmed Al-Mansouri/);
    expect(".o_hotel_dashboard_drawer").toHaveText(/Double Suite/);
    await contains('[data-dashboard-drawer-action="amendment"]').click();
    expect(".o_hotel_dashboard_drawer").toHaveCount(0);
    expect(openedAction).toMatchObject({
        res_model: "hotel.reservation.amendment",
        context: {
            default_reservation_id: 72,
            default_property_id: PROPERTY_ID,
            hotel_property_id: PROPERTY_ID,
            business_date: BUSINESS_DATE,
            hotel_business_date: BUSINESS_DATE,
        },
    });

    await contains(".o_hotel_text_action").click();
    await contains('[data-dashboard-drawer-action="reservation"]').click();
    expect(".o_hotel_dashboard_drawer").toHaveCount(0);
    expect(openedAction.context).toMatchObject({
        default_property_id: PROPERTY_ID,
        hotel_property_id: PROPERTY_ID,
        business_date: BUSINESS_DATE,
        hotel_business_date: BUSINESS_DATE,
    });

    await contains('[data-dashboard-activity="departures"]').click();
    await animationFrame();
    expect(activityArgs).toEqual([false, BUSINESS_DATE, "departures", false, false, 50]);
    expect(".o_hotel_activity_empty").toHaveCount(1);
});

test("Dashboard keeps the last activity visible when a refresh fails", async () => {
    let requestCount = 0;
    mockFrontdeskState();
    mockAction();
    onRpc("hotel.frontdesk.workspace", "get_dashboard_snapshot", () => {
        requestCount += 1;
        if (requestCount === 1) {
            return dashboardSnapshot();
        }
        throw new Error("Network unavailable");
    });

    const dashboard = await mountWithCleanup(HotelDashboard, {
        props: {
            action: {
                context: {
                    default_property_id: PROPERTY_ID,
                    default_business_date: BUSINESS_DATE,
                },
            },
        },
    });
    await animationFrame();
    expect(".o_hotel_activity_row").toHaveCount(1);

    // The dashboard refreshes silently on a timer; simulate one tick.
    await dashboard.refreshDashboard({ background: true });
    await animationFrame();
    expect(".o_hotel_activity_row").toHaveCount(1);
    expect(".o_hotel_dashboard_stale").toHaveCount(1);
});

test("Dashboard ignores an older snapshot that resolves after a newer refresh", async () => {
    const older = new Deferred();
    const newer = new Deferred();
    const requests = [older, newer];
    mockFrontdeskState();
    mockAction();
    onRpc("hotel.frontdesk.workspace", "get_dashboard_snapshot", () => requests.shift());

    const dashboard = await mountWithCleanup(HotelDashboard, {
        props: {
            action: { context: { default_business_date: BUSINESS_DATE } },
        },
    });
    dashboard.refreshDashboard({ background: true });
    const newerSnapshot = dashboardSnapshot();
    newerSnapshot.occupancy.percentage = 75;
    newer.resolve(newerSnapshot);
    await animationFrame();
    older.resolve(dashboardSnapshot());
    await animationFrame();
    expect(".o_hotel_occupancy_ring").toHaveText(/75%/);
});

test("Dashboard executes direct check-in once and refreshes the snapshot", async () => {
    let workflowCalls = 0;
    const workflow = new Deferred();
    mockFrontdeskState();
    mockAction();
    onRpc("hotel.frontdesk.workspace", "get_dashboard_snapshot", () => dashboardSnapshot());
    onRpc("hotel.reservation", "action_check_in", ({ args }) => {
        workflowCalls += 1;
        expect(args).toEqual([[72]]);
        return workflow;
    });

    await mountWithCleanup(HotelDashboard, {
        props: {
            action: { context: { default_business_date: BUSINESS_DATE } },
        },
    });
    await animationFrame();
    const button = document.querySelector(".o_hotel_primary_workflow");
    button.click();
    button.click();
    await animationFrame();
    expect(workflowCalls).toBe(1);
    expect(".o_hotel_primary_workflow").toHaveAttribute("disabled");
    workflow.resolve(true);
    await animationFrame();
    expect(".o_hotel_activity_row").toHaveCount(1);
});

test("Dashboard date controls request the adjacent business day", async () => {
    const requestedDates = [];
    mockFrontdeskState();
    mockAction();
    onRpc("hotel.frontdesk.workspace", "get_dashboard_snapshot", ({ args }) => {
        requestedDates.push(args[1]);
        return dashboardSnapshot(args[1]);
    });

    await mountWithCleanup(HotelDashboard, {
        props: {
            action: { context: { default_business_date: BUSINESS_DATE } },
        },
    });
    await animationFrame();
    await contains('button[aria-label="Next day"]').click();
    await animationFrame();
    expect(requestedDates).toEqual([BUSINESS_DATE, "2026-07-14"]);
    expect(".o_hotel_date_day").toHaveText("14");
});

test("Dashboard activity search is debounced before reaching the server", async () => {
    const activityRequests = [];
    mockFrontdeskState();
    mockAction();
    onRpc("hotel.frontdesk.workspace", "get_dashboard_snapshot", () => dashboardSnapshot());
    onRpc("hotel.frontdesk.workspace", "get_dashboard_activity", ({ args }) => {
        activityRequests.push(args);
        return dashboardSnapshot().activity;
    });

    await mountWithCleanup(HotelDashboard, {
        props: {
            action: { context: { default_business_date: BUSINESS_DATE } },
        },
    });
    await animationFrame();
    await contains('button[aria-label="Search activity"]').click();
    await contains("#hotel-dashboard-search").edit("Ahmed", { confirm: false });
    await advanceTime(299);
    expect(activityRequests).toHaveLength(0);
    await advanceTime(1);
    expect(activityRequests).toHaveLength(1);
    expect(activityRequests[0]).toEqual([
        false,
        BUSINESS_DATE,
        "arrivals",
        false,
        "Ahmed",
        50,
    ]);
});

test("Dashboard completed-arrival toggle requests the expanded activity", async () => {
    let activityArgs;
    mockFrontdeskState();
    mockAction();
    onRpc("hotel.frontdesk.workspace", "get_dashboard_snapshot", () => dashboardSnapshot());
    onRpc("hotel.frontdesk.workspace", "get_dashboard_activity", ({ args }) => {
        activityArgs = args;
        return { ...dashboardSnapshot().activity, include_completed: true };
    });

    await mountWithCleanup(HotelDashboard, {
        props: {
            action: { context: { default_business_date: BUSINESS_DATE } },
        },
    });
    await animationFrame();
    await contains(".o_hotel_completed_toggle input").click();
    await animationFrame();
    expect(activityArgs).toEqual([false, BUSINESS_DATE, "arrivals", true, false, 50]);
});

test("Planning exposes read-only cells to RTL arrow-key navigation", async () => {
    const previousDirection = document.documentElement.dir;
    document.documentElement.dir = "rtl";
    after(() => {
        document.documentElement.dir = previousDirection;
    });
    mockFrontdeskState();
    mockAction();
    onRpc("hotel.frontdesk.workspace", "get_planning_window", ({ args }) => {
        expect(args.slice(0, 3)).toEqual([false, BUSINESS_DATE, 7]);
        return planningWindow();
    });

    await mountWithCleanup(HotelPlanning, {
        props: {
            action: {
                context: {
                    default_property_id: PROPERTY_ID,
                    default_start_date: BUSINESS_DATE,
                    default_day_count: 7,
                },
            },
        },
    });
    await animationFrame();

    expect(".o_today_marker").toHaveText("Today");
    expect(".o_business_marker").toHaveText("Business Date");
    expect(".o_hotel_planning_cell").toHaveCount(2);
    expect(".o_hotel_planning_cell:eq(0)").toHaveAttribute("aria-disabled", "true");
    expect(".o_hotel_planning_cell:eq(0)").not.toHaveAttribute("disabled");
    expect(
        globalThis.getComputedStyle(document.querySelector(".o_hotel_planning_tape")).direction
    ).toBe("rtl");

    await contains(".o_hotel_planning_tape").focus();
    await contains(".o_hotel_planning_tape").press("ArrowLeft");
    expect(".o_hotel_planning_cell:eq(0)").toBeFocused();
    expect(document.activeElement.getAttribute("aria-label")).toInclude("Today");

    await contains(".o_hotel_planning_cell:eq(0)").press("ArrowLeft");
    expect(".o_hotel_planning_cell:eq(1)").toBeFocused();
});
