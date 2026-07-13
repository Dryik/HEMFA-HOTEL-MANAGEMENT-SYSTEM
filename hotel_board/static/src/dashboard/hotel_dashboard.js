import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const REFRESH_INTERVAL_MS = 60_000;

export class HotelDashboard extends Component {
    static template = "hotel_board.HotelDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            data: null,
            loading: true,
            error: null,
            propertyId: null,
            businessDate: null,
        });
        this._refreshTimer = null;
        this._request = null;
        this._requestSequence = 0;
        this._destroyed = false;
        onWillStart(() => this.loadData());
        onMounted(() => {
            this._refreshTimer = setInterval(() => this.loadData(), REFRESH_INTERVAL_MS);
        });
        onWillUnmount(() => {
            this._destroyed = true;
            if (this._refreshTimer) {
                clearInterval(this._refreshTimer);
            }
            if (this._request?.abort) {
                this._request.abort(false);
            }
        });
    }

    async loadData() {
        if (this._request?.abort) {
            this._request.abort(false);
        }
        const requestSequence = ++this._requestSequence;
        this.state.loading = true;
        this.state.error = null;
        const args = [this.state.propertyId || false, this.state.businessDate || false];
        try {
            this._request = this.orm.silent.call(
                "hotel.reservation",
                "get_dashboard_data",
                args
            );
            const data = await this._request;
            if (this._destroyed || requestSequence !== this._requestSequence) {
                return;
            }
            this.state.data = data;
            this.state.propertyId = data.property_id;
            this.state.businessDate = data.business_date;
        } catch (error) {
            if (
                !this._destroyed &&
                requestSequence === this._requestSequence &&
                error.name !== "ConnectionAbortedError"
            ) {
                this.state.error = error.message || "Unable to refresh the room board.";
            }
        } finally {
            if (!this._destroyed && requestSequence === this._requestSequence) {
                this.state.loading = false;
                this._request = null;
            }
        }
    }

    onPropertyChange(event) {
        this.state.propertyId = Number(event.target.value);
        this.loadData();
    }

    onDateChange(event) {
        this.state.businessDate = event.target.value;
        this.loadData();
    }

    openAction(xmlid) {
        this.action.doAction(xmlid);
    }

    openRooms(filterName) {
        const propertyId = this.state.data?.property_id;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Rooms",
            res_model: "hotel.room",
            views: [[false, "kanban"], [false, "list"], [false, "form"]],
            context: filterName ? { [`search_default_${filterName}`]: 1 } : {},
            domain: propertyId ? [["property_id", "=", propertyId]] : [],
        });
    }

    openBoardItem(item) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: item.reservation_id ? "Reservation" : "Room",
            res_model: item.reservation_id ? "hotel.reservation" : "hotel.room",
            views: [[false, "form"]],
            res_id: item.reservation_id || item.room_id,
        });
    }

    newReservation() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Reservation",
            res_model: "hotel.reservation",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_property_id: this.state.data?.property_id,
            },
        });
    }
}

registry.category("actions").add("hotel_board.dashboard", HotelDashboard);
