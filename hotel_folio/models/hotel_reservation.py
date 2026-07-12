from odoo import _, api, fields, models


class HotelReservation(models.Model):
    _inherit = "hotel.reservation"

    folio_ids = fields.One2many(
        "hotel.folio", "reservation_id", string="Folios"
    )
    folio_count = fields.Integer(
        string="Folio Count", compute="_compute_folio_count"
    )

    @api.depends("folio_ids")
    def _compute_folio_count(self):
        for rec in self:
            rec.folio_count = len(rec.folio_ids)

    def action_confirm(self):
        super().action_confirm()
        for rec in self:
            if not rec.folio_ids:
                self.env["hotel.folio"].create(
                    {
                        "reservation_id": rec.id,
                    }
                )

    def action_view_folios(self):
        self.ensure_one()
        action = {
            "name": _("Folios"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.folio",
            "view_mode": "list,form",
            "domain": [("reservation_id", "=", self.id)],
            "context": {"default_reservation_id": self.id},
        }
        if len(self.folio_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": self.folio_ids[0].id,
                }
            )
        return action
