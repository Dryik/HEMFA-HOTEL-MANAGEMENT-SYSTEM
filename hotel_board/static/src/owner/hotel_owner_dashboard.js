import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { formatCurrency, formatNumber } from "../shared/frontdesk_utils";

export class HotelOwnerDashboard extends Component {
    static template = "hotel_board.HotelOwnerDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            data: null,
            propertyId: this.props.action?.context?.default_property_id || null,
            dateFrom: this.props.action?.context?.date_from || null,
            dateTo: this.props.action?.context?.date_to || null,
            error: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call("hotel.owner.dashboard", "get_dashboard", [], {
                property_id: this.state.propertyId,
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
            });
            this.state.data = data;
            this.state.propertyId = data.meta.property_id;
            this.state.dateFrom = data.meta.date_from;
            this.state.dateTo = data.meta.date_to;
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || String(error);
        } finally {
            this.state.loading = false;
        }
    }

    onDateFrom(event) {
        this.state.dateFrom = event.target.value;
    }

    onProperty(event) {
        this.state.propertyId = Number(event.target.value) || null;
    }

    onDateTo(event) {
        this.state.dateTo = event.target.value;
    }

    currency(value) {
        return formatCurrency(value, this.state.data?.meta.currency);
    }

    number(value, digits = 0) {
        return formatNumber(value, { maximumFractionDigits: digits });
    }

    trendWidth(value, field) {
        const maximum = Math.max(...this.state.data.trends.map((item) => Number(item[field] || 0)), 1);
        return `${Math.max((Number(value || 0) / maximum) * 100, value ? 3 : 0)}%`;
    }
}

registry.category("actions").add("hotel_board.owner_dashboard", HotelOwnerDashboard);
