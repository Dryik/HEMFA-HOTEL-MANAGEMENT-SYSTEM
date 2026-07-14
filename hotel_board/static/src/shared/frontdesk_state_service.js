import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { session } from "@web/session";

export const FRONTDESK_STORAGE_KEY = "hotel_board.frontdesk_context.v2";

function normaliseDate(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(value || "") ? value : null;
}

function readStoredState(storage, storageKey) {
    try {
        const value = JSON.parse(storage.getItem(storageKey) || "{}");
        return {
            businessDate: normaliseDate(value.businessDate),
        };
    } catch {
        return { businessDate: null };
    }
}

export function createFrontdeskStateStore(
    storage = browser.sessionStorage,
    scopeProvider = () => ""
) {
    const scopedKey = () => {
        const scope = String(scopeProvider?.() || "").replace(/[^a-zA-Z0-9_.-]/g, "_");
        return scope ? `${FRONTDESK_STORAGE_KEY}.${scope}` : FRONTDESK_STORAGE_KEY;
    };
    let storageKey = scopedKey();
    let state = readStoredState(storage, storageKey);

    function ensureScope() {
        const nextKey = scopedKey();
        if (nextKey !== storageKey) {
            storageKey = nextKey;
            state = readStoredState(storage, storageKey);
        }
    }

    function persist() {
        try {
            storage.setItem(storageKey, JSON.stringify(state));
        } catch {
            // A blocked storage backend must not prevent front-desk work.
        }
    }

    return {
        get() {
            ensureScope();
            return { ...state };
        },
        update(values = {}) {
            ensureScope();
            state = {
                businessDate:
                    values.businessDate === undefined
                        ? state.businessDate
                        : normaliseDate(values.businessDate),
            };
            persist();
            return { ...state };
        },
    };
}

export function seedFrontdeskState(store, defaults = {}) {
    const state = store.get();
    if (state.businessDate) {
        return state;
    }
    return store.update({
        businessDate: defaults.hotel_business_date,
    });
}

const frontdeskStateService = {
    start() {
        const store = createFrontdeskStateStore(browser.sessionStorage, () =>
            [session.db || "database", user.userId || 0, user.activeCompany?.id || 0].join(".")
        );
        const syncContext = (state) => {
            user.updateContext({
                hotel_business_date: state.businessDate || false,
            });
            return state;
        };
        syncContext(seedFrontdeskState(store, user.context || {}));
        return {
            get() {
                return syncContext(store.get());
            },
            update(values) {
                return syncContext(store.update(values));
            },
        };
    },
};

registry.category("services").add("hotel_frontdesk_state", frontdeskStateService);
