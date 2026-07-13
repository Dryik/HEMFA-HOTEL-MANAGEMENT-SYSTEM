import { describe, expect, test } from "@odoo/hoot";

import {
    assignReservationLanes,
    normaliseBar,
    normalisePlanning,
} from "@hotel_board/planning/hotel_planning";
import {
    actionWithFrontdeskContext,
    addIsoDays,
    formatOperationalDateTime,
    refreshFailureViewState,
    westernDigits,
} from "@hotel_board/shared/frontdesk_utils";
import {
    createFrontdeskStateStore,
    FRONTDESK_STORAGE_KEY,
    seedFrontdeskState,
} from "@hotel_board/shared/frontdesk_state_service";

describe.current.tags("headless");

function makeStorage(initialValue = null) {
    const values = new Map();
    if (initialValue !== null) {
        values.set(FRONTDESK_STORAGE_KEY, initialValue);
    }
    return {
        getItem(key) {
            return values.get(key) ?? null;
        },
        setItem(key, value) {
            values.set(key, String(value));
        },
    };
}

test("operational values always use Western digits", () => {
    expect(westernDigits("Room ١٢٣ / ۴۵۶")).toBe("Room 123 / 456");
    expect(addIsoDays("2026-07-31", 1)).toBe("2026-08-01");
});

test("Front Desk context is persisted and invalid storage is ignored", () => {
    const storage = makeStorage("not-json");
    const store = createFrontdeskStateStore(storage);
    expect(store.get()).toEqual({ propertyId: null, businessDate: null });

    store.update({ propertyId: "9", businessDate: "2026-07-13" });
    expect(store.get()).toEqual({ propertyId: 9, businessDate: "2026-07-13" });

    const restored = createFrontdeskStateStore(storage);
    expect(restored.get()).toEqual({ propertyId: 9, businessDate: "2026-07-13" });
});

test("Front Desk context is isolated by database, user, and company scope", () => {
    const storage = makeStorage();
    let scope = "hotel.7.3";
    const store = createFrontdeskStateStore(storage, () => scope);

    store.update({ propertyId: 4, businessDate: "2026-07-13" });
    scope = "hotel.8.3";
    expect(store.get()).toEqual({ propertyId: null, businessDate: null });

    store.update({ propertyId: 9, businessDate: "2026-07-14" });
    scope = "hotel.7.3";
    expect(store.get()).toEqual({ propertyId: 4, businessDate: "2026-07-13" });
});

test("an empty scoped store adopts server Front Desk defaults once", () => {
    const store = createFrontdeskStateStore(makeStorage(), () => "hotel.7.3");
    expect(
        seedFrontdeskState(store, {
            hotel_property_id: 4,
            hotel_business_date: "2026-07-13",
        })
    ).toEqual({ propertyId: 4, businessDate: "2026-07-13" });

    expect(
        seedFrontdeskState(store, {
            hotel_property_id: 9,
            hotel_business_date: "2026-08-01",
        })
    ).toEqual({ propertyId: 4, businessDate: "2026-07-13" });
});

test("actions receive the full selected Front Desk context without mutation", () => {
    const source = {
        type: "ir.actions.act_window",
        res_model: "hotel.reservation",
        context: {
            search_default_arrivals: 1,
            default_property_id: 99,
            hotel_property_id: 99,
            business_date: "2020-01-01",
        },
    };
    const action = actionWithFrontdeskContext(source, 4, "2026-07-13");

    expect(action.context).toEqual({
        default_property_id: 4,
        hotel_property_id: 4,
        business_date: "2026-07-13",
        hotel_business_date: "2026-07-13",
        default_business_date: "2026-07-13",
        search_default_arrivals: 1,
    });
    expect(source.context).toEqual({
        search_default_arrivals: 1,
        default_property_id: 99,
        hotel_property_id: 99,
        business_date: "2020-01-01",
    });
});

test("planning bars are clipped to the visible range", () => {
    const bar = normaliseBar(
        { id: 12, state: "confirmed", start_index: -2, span: 5 },
        "2026-07-13",
        14
    );
    expect(bar.gridStart).toBe(1);
    expect(bar.gridSpan).toBe(3);
    expect(bar.stateClass).toBe("confirmed");
});

test("overlapping planning bars are assigned separate reusable lanes", () => {
    const bars = [
        normaliseBar({ id: 1, start_index: 0, span: 3 }, "2026-07-13", 14),
        normaliseBar({ id: 2, start_index: 1, span: 2 }, "2026-07-13", 14),
        normaliseBar({ id: 3, start_index: 3, span: 2 }, "2026-07-13", 14),
    ];

    expect(assignReservationLanes(bars)).toBe(2);
    expect(bars.map((bar) => bar.lane)).toEqual([0, 1, 0]);
});

test("operational datetimes convert UTC values into the property timezone", () => {
    expect(formatOperationalDateTime("2026-07-13 10:00:00", "Africa/Tripoli")).toBe(
        "13/07/2026 12:00"
    );
});

test("planning normalisation builds a complete requested date range", () => {
    const planning = normalisePlanning(
        {
            meta: { property_id: 3, start_date: "2026-07-13", day_count: 7 },
            floors: [{ id: 1, name: "First", rows: [{ id: 101, name: "101" }] }],
        },
        "2026-07-13",
        7
    );

    expect(planning.days).toHaveLength(7);
    expect(planning.days[6].date).toBe("2026-07-19");
    expect(planning.floors[0].rows[0].id).toBe(101);
});

test("a refresh failure preserves the last successful payload and marks it stale", () => {
    const lastSuccessfulData = { version: 1, floors: [{ id: 1 }] };
    const state = refreshFailureViewState(lastSuccessfulData, "Offline");

    expect(state.data).toBe(lastSuccessfulData);
    expect(state.error).toBe("Offline");
    expect(state.stale).toBe(true);
});
