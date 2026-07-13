from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HotelReservation(models.Model):
    _inherit = "hotel.reservation"

    rate_locked = fields.Boolean(
        string="Rate Locked",
        default=False,
        tracking=True,
        help="If checked, nightly rate will not be updated automatically by seasonal pricing or occupancy bands.",
    )

    @api.depends("room_type_id", "room_id", "checkin_date", "partner_id", "rate_locked")
    def _compute_rate_night(self):
        # First group by rate_locked to handle inheritance properly
        locked_recs = self.filtered("rate_locked")
        # For locked records, do not change the rate_night if it is already set
        for rec in locked_recs:
            if not rec.rate_night:
                # If it's locked but not set, compute it once
                super(HotelReservation, rec)._compute_rate_night()

        unlocked_recs = self - locked_recs
        for rec in unlocked_recs:
            rtype = rec.room_type_id or rec.room_id.room_type_id
            if not rtype:
                rec.rate_night = 0.0
                continue

            # Determine base price from seasonal rate rules
            base_price = rtype.base_price
            checkin_date = rec.checkin_date
            if checkin_date:
                checkin_date_only = rec.property_id.get_business_date(checkin_date)
                guest_nationality = rec.guest_nationality_id.code

                domain = [
                    ("property_id", "=", rec.property_id.id),
                    ("room_type_id", "=", rtype.id),
                    ("date_start", "<=", checkin_date_only),
                    ("date_end", ">=", checkin_date_only),
                ]
                if guest_nationality == "LY":
                    domain.append(("guest_type", "in", ("all", "local")))
                elif guest_nationality:
                    domain.append(("guest_type", "in", ("all", "foreign")))
                else:
                    domain.append(("guest_type", "=", "all"))

                rule = self.env["hotel.rate.rule"].search(domain, order="sequence, id", limit=1)
                if rule:
                    if rule.currency_id != rec.currency_id:
                        base_price = rule.currency_id._convert(
                            rule.rate_price,
                            rec.currency_id,
                            rec.property_id.company_id or self.env.company,
                            checkin_date_only,
                        )
                    else:
                        base_price = rule.rate_price

                # Calculate occupancy band adjustment
                # Count reservations overlapping the check-in date
                # We exclude this reservation if it's already in the database and state is confirmed/checked_in
                occupied_domain = [
                    ("property_id", "=", rec.property_id.id),
                    ("state", "in", ("confirmed", "checked_in")),
                    ("checkin_date", "<=", checkin_date),
                    ("checkout_date", ">", checkin_date),
                ]
                if rec.id and isinstance(rec.id, int):
                    occupied_domain.append(("id", "!=", rec.id))
                
                occupied_rooms = self.env["hotel.reservation"].search_count(occupied_domain)
                sellable_rooms = self.env["hotel.room"].search_count(
                    [
                        ("property_id", "=", rec.property_id.id),
                        ("is_sellable", "=", True),
                    ]
                )
                
                occupancy_pct = (
                    (100.0 * occupied_rooms / sellable_rooms) if sellable_rooms else 0.0
                )

                band = self.env["hotel.rate.occupancy.band"].search(
                    [
                        ("property_id", "=", rec.property_id.id),
                        ("min_occupancy", "<=", occupancy_pct),
                        ("max_occupancy", ">=", occupancy_pct),
                    ],
                    limit=1,
                )
                multiplier = band.multiplier if band else 1.0
                rec.rate_night = base_price * multiplier
            else:
                rec.rate_night = base_price

    def action_confirm(self):
        super().action_confirm()
        self._set_confirmed_rate_lock()

    def _set_confirmed_rate_lock(self):
        return super(HotelReservation, self).write({"rate_locked": True})

    def write(self, vals):
        if "rate_locked" in vals and not (
            self.env.su and self.env.context.get("hotel_migration")
        ):
            raise UserError(_("Confirmed-rate locking is controlled by hotel workflows."))
        return super().write(vals)
