/** Booking basket summary for the public rooms page.
 *
 * The page is server-rendered; this widget only aggregates the quantities the
 * guest typed into the room and service cards so the total is visible before
 * "Continue booking". Amounts come from data attributes rendered by QWeb —
 * the server re-quotes everything on submission, so this is display-only.
 */
(function () {
    "use strict";

    function formatAmount(amount, currencySymbol, position) {
        const value = amount.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
        return position === "before" ? `${currencySymbol} ${value}` : `${value} ${currencySymbol}`;
    }

    function setup() {
        const summary = document.querySelector(".o_hotel_booking_summary");
        if (!summary) {
            return;
        }
        const roomInputs = Array.from(document.querySelectorAll("input[data-hotel-room-price]"));
        const serviceInputs = Array.from(document.querySelectorAll("input[data-hotel-service-price]"));
        const roomsOut = summary.querySelector("[data-summary-rooms]");
        const servicesOut = summary.querySelector("[data-summary-services]");
        const totalOut = summary.querySelector("[data-summary-total]");
        const currencySymbol = summary.dataset.currencySymbol || "";
        const currencyPosition = summary.dataset.currencyPosition || "after";

        function refresh() {
            let roomCount = 0;
            let total = 0;
            for (const input of roomInputs) {
                const qty = Math.max(0, parseInt(input.value, 10) || 0);
                roomCount += qty;
                total += qty * (parseFloat(input.dataset.hotelRoomPrice) || 0);
            }
            let serviceCount = 0;
            for (const input of serviceInputs) {
                const qty = Math.max(0, parseInt(input.value, 10) || 0);
                serviceCount += qty;
                total += qty * (parseFloat(input.dataset.hotelServicePrice) || 0);
            }
            roomsOut.textContent = String(roomCount);
            servicesOut.textContent = String(serviceCount);
            totalOut.textContent = formatAmount(total, currencySymbol, currencyPosition);
            summary.classList.toggle("d-none", roomCount === 0 && serviceCount === 0);
        }

        for (const input of roomInputs.concat(serviceInputs)) {
            input.addEventListener("input", refresh);
            input.addEventListener("change", refresh);
        }
        refresh();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setup);
    } else {
        setup();
    }
})();
