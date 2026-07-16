import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

export class HotelStayDialog extends Component {
    static template = "hotel_pos_room_charge.HotelStayDialog";
    static components = { Dialog };
    static props = {
        candidates: Array,
        getPayload: Function,
        close: Function,
    };

    setup() {
        this.state = useState({ query: "" });
    }

    get matches() {
        const query = this.state.query.trim().toLocaleLowerCase();
        if (!query) {
            return this.props.candidates;
        }
        return this.props.candidates.filter((candidate) =>
            [candidate.guest, candidate.reservation, candidate.room, candidate.room_type]
                .join(" ")
                .toLocaleLowerCase()
                .includes(query)
        );
    }

    select(candidate) {
        this.props.getPayload(candidate);
        this.props.close();
    }
}

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
    },

    get hasHotelRoomCharge() {
        return this.pos.config.payment_method_ids.some((method) => method.is_room_charge);
    },

    async selectHotelStay() {
        const candidates = await this.orm.call(
            "pos.config",
            "get_hotel_room_charge_candidates",
            [this.pos.config.id]
        );
        const candidate = await makeAwaitable(this.dialog, HotelStayDialog, { candidates });
        if (!candidate) {
            return;
        }
        let partner = this.pos.models["res.partner"].get(candidate.partner_id);
        if (!partner) {
            await this.pos.data.callRelated("res.partner", "get_new_partner", [
                this.pos.config.id,
                [["id", "=", candidate.partner_id]],
                0,
            ]);
            partner = this.pos.models["res.partner"].get(candidate.partner_id);
        }
        if (!partner) {
            this.notification.add(_t("The hotel guest could not be loaded."), { type: "danger" });
            return;
        }
        this.pos.setPartnerToCurrentOrder(partner);
        this.notification.add(
            _t("Room %s selected. Choose Pay at Checkout on the payment screen.", candidate.room),
            { type: "success" }
        );
        this.props.close?.();
    },
});
