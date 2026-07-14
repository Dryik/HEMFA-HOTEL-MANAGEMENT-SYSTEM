import { after, describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
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

function dashboardSnapshot() {
    return {
        version: 1,
        meta: {
            property_id: PROPERTY_ID,
            property_name: "Tripoli Hotel",
            business_date: BUSINESS_DATE,
            timezone: "Africa/Tripoli",
            metric_label: "Forecast",
            currency: {
                name: "LYD",
                symbol: "LYD",
                position: "after",
                decimal_places: 3,
            },
        },
        properties: [
            { id: PROPERTY_ID, name: "Tripoli Hotel" },
            { id: 3, name: "Coastal Hotel" },
        ],
        kpis: {
            arrivals: {
                label: "Arrivals",
                value: 2,
                available: true,
                format: "integer",
                action: {
                    type: "ir.actions.act_window",
                    res_model: "hotel.reservation",
                    context: {
                        hotel_property_id: 99,
                        business_date: "2020-01-01",
                    },
                },
            },
        },
        attention: { total: 0, items: [] },
        floors: [
            {
                id: 1,
                name: "First Floor",
                rooms: [
                    {
                        id: 101,
                        name: "101",
                        room_type: { id: 10, name: "King" },
                        primary_status: "vacant",
                        primary_label: "Vacant",
                        hk_status: "clean",
                        hk_label: "Clean",
                        alerts: [],
                    },
                ],
            },
        ],
        legend: { primary: [], housekeeping: [], alerts: [] },
        actions: {},
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

test("Dashboard renders loading data and opens drill-downs with snapshot context", async () => {
    const response = new Deferred();
    const getFrontdeskState = mockFrontdeskState();
    let openedAction;
    mockAction((action) => {
        openedAction = action;
    });
    onRpc(
        "hotel.frontdesk.workspace",
        "get_workspace_snapshot",
        ({ args }) => {
            expect(args).toEqual([false, BUSINESS_DATE]);
            return response;
        }
    );

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
    expect(".o_hotel_loading_state").toHaveCount(1);

    response.resolve(dashboardSnapshot());
    await animationFrame();
    expect(".o_hotel_loading_state").toHaveCount(0);
    expect(".o_hotel_room_tile").toHaveText(/101/);
    expect(getFrontdeskState()).toEqual({
        businessDate: BUSINESS_DATE,
    });

    await contains(".o_hotel_kpi_button").click();
    expect(openedAction.context).toMatchObject({
        default_property_id: PROPERTY_ID,
        hotel_property_id: PROPERTY_ID,
        business_date: BUSINESS_DATE,
        hotel_business_date: BUSINESS_DATE,
    });
});

test("Dashboard keeps the last snapshot visible when a refresh fails", async () => {
    let requestCount = 0;
    mockFrontdeskState();
    mockAction();
    onRpc("hotel.frontdesk.workspace", "get_workspace_snapshot", () => {
        requestCount += 1;
        if (requestCount === 1) {
            return dashboardSnapshot();
        }
        throw new Error("Network unavailable");
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
    await animationFrame();
    expect(".o_hotel_room_tile").toHaveCount(1);

    await contains(".o_hotel_header_actions button:first-child").click();
    await animationFrame();
    expect(".o_hotel_room_tile").toHaveCount(1);
    expect(".o_hotel_workspace_alert.alert-danger").toHaveCount(1);
    expect(".o_hotel_workspace_alert.alert-warning").toHaveCount(1);
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
