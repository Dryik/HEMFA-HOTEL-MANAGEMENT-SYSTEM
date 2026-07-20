import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";

const NUMBER_FORMATTERS = new Map();

function localeCode() {
    try {
        return localization.code?.replaceAll("_", "-") || undefined;
    } catch {
        return undefined;
    }
}

export function asArray(value) {
    return Array.isArray(value) ? value : [];
}

export function asId(value) {
    if (Array.isArray(value)) {
        value = value[0];
    } else if (value && typeof value === "object") {
        value = value.id;
    }
    const id = Number(value);
    return Number.isInteger(id) && id > 0 ? id : null;
}

export function isoDate(value) {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    return match ? match[0] : null;
}

export function addIsoDays(value, dayCount) {
    const dateValue = isoDate(value);
    if (!dateValue) {
        return null;
    }
    const [year, month, day] = dateValue.split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1, day + dayCount));
    return [
        date.getUTCFullYear(),
        String(date.getUTCMonth() + 1).padStart(2, "0"),
        String(date.getUTCDate()).padStart(2, "0"),
    ].join("-");
}

export function atNoon(value) {
    const dateValue = isoDate(value);
    return dateValue ? `${dateValue} 12:00:00` : false;
}

export function westernDigits(value) {
    const arabic = "٠١٢٣٤٥٦٧٨٩";
    const persian = "۰۱۲۳۴۵۶۷۸۹";
    return String(value ?? "")
        .replace(/[٠-٩]/g, (digit) => String(arabic.indexOf(digit)))
        .replace(/[۰-۹]/g, (digit) => String(persian.indexOf(digit)));
}

export function formatNumber(value, options = {}) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
        return "—";
    }
    const locale = localeCode();
    const key = JSON.stringify([locale, options]);
    if (!NUMBER_FORMATTERS.has(key)) {
        NUMBER_FORMATTERS.set(
            key,
            new Intl.NumberFormat(locale, { numberingSystem: "latn", ...options })
        );
    }
    return westernDigits(NUMBER_FORMATTERS.get(key).format(number));
}

export function formatCurrency(value, currency = {}) {
    const amount = formatNumber(value, {
        minimumFractionDigits: Number(currency.decimal_places ?? 2),
        maximumFractionDigits: Number(currency.decimal_places ?? 2),
    });
    const symbol = currency.symbol || currency.name || "";
    return currency.position === "before"
        ? `${symbol}${symbol ? "\u00a0" : ""}${amount}`
        : `${amount}${symbol ? "\u00a0" : ""}${symbol}`;
}

export function formatOperationalDateTime(value, timezone = null) {
    const match = String(value || "").match(
        /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/
    );
    if (!match) {
        return value ? westernDigits(value) : "";
    }
    const [, year, month, day, hour, minute] = match;
    if (!hour) {
        return `${day}/${month}/${year}`;
    }
    try {
        return westernDigits(
            deserializeDateTime(value, { tz: timezone || undefined }).toFormat(
                "dd/MM/yyyy HH:mm"
            )
        );
    } catch {
        return `${day}/${month}/${year} ${hour}:${minute}`;
    }
}

export function formatWeekday(value) {
    const dateValue = isoDate(value);
    if (!dateValue) {
        return "";
    }
    const [year, month, day] = dateValue.split("-").map(Number);
    return westernDigits(
        new Intl.DateTimeFormat(localeCode(), {
            weekday: "short",
            timeZone: "UTC",
            numberingSystem: "latn",
        }).format(new Date(Date.UTC(year, month - 1, day)))
    );
}

export function formatBusinessDateParts(value) {
    const dateValue = isoDate(value);
    if (!dateValue) {
        return { weekday: "", day: "", month: "", year: "" };
    }
    const [year, month, day] = dateValue.split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    const options = { timeZone: "UTC", numberingSystem: "latn" };
    return {
        weekday: westernDigits(
            new Intl.DateTimeFormat(localeCode(), { ...options, weekday: "long" }).format(date)
        ),
        day: westernDigits(
            new Intl.DateTimeFormat(localeCode(), { ...options, day: "numeric" }).format(date)
        ),
        month: westernDigits(
            new Intl.DateTimeFormat(localeCode(), { ...options, month: "long" }).format(date)
        ),
        year: westernDigits(
            new Intl.DateTimeFormat(localeCode(), { ...options, year: "numeric" }).format(date)
        ),
    };
}

export function actionWithFrontdeskContext(action, propertyId, businessDate) {
    if (!action || typeof action !== "object") {
        return action;
    }
    return {
        ...action,
        context: {
            ...(action.context || {}),
            default_property_id: propertyId || false,
            hotel_property_id: propertyId || false,
            business_date: businessDate || false,
            hotel_business_date: businessDate || false,
            default_business_date: businessDate || false,
        },
    };
}

export function errorMessage(error, fallback = _t("Unable to refresh this workspace.")) {
    return error?.data?.message || error?.message || fallback;
}

export function refreshFailureViewState(currentData, message) {
    return {
        data: currentData || null,
        error: message,
        stale: Boolean(currentData),
    };
}
