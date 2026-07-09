import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class HotelDashboard extends Component {
    static template = "hotel_board.HotelDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.data = await this.orm.call(
            "hotel.reservation",
            "get_dashboard_data",
            []
        );
    }

    openAction(xmlid) {
        this.action.doAction(xmlid);
    }

    openRooms(filterName) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Rooms",
            res_model: "hotel.room",
            views: [
                [false, "kanban"],
                [false, "list"],
                [false, "form"],
            ],
            context: filterName ? { [`search_default_${filterName}`]: 1 } : {},
        });
    }

    newReservation() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Reservation",
            res_model: "hotel.reservation",
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("hotel_board.dashboard", HotelDashboard);
