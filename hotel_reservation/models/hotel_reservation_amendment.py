from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HotelReservationAmendment(models.Model):
    _name = "hotel.reservation.amendment"
    _description = "Immutable Reservation Amendment"
    _inherit = ["mail.thread"]
    _order = "effective_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    reservation_id = fields.Many2one(
        "hotel.reservation", required=True, ondelete="restrict", index=True
    )
    property_id = fields.Many2one(
        related="reservation_id.property_id", store=True, readonly=True
    )
    amendment_type = fields.Selection(
        [
            ("room_move", "Room Move"),
            ("extend", "Extend Stay"),
            ("shorten", "Shorten Stay"),
            ("early_checkin", "Early Check-in"),
            ("late_checkout", "Late Checkout"),
            ("day_use", "Day Use"),
            ("reprice", "Manager Repricing"),
        ],
        required=True,
    )
    effective_date = fields.Datetime(required=True, default=fields.Datetime.now)
    reason = fields.Text(required=True)
    new_room_id = fields.Many2one(
        "hotel.room",
        domain="[('property_id', '=', property_id), ('is_sellable', '=', True)]",
    )
    new_checkin_date = fields.Datetime()
    new_checkout_date = fields.Datetime()
    new_rate_night = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="reservation_id.currency_id")
    before_values = fields.Json(readonly=True, copy=False)
    after_values = fields.Json(readonly=True, copy=False)
    requested_by_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, readonly=True
    )
    approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    state = fields.Selection(
        [("draft", "Draft"), ("applied", "Applied")],
        default="draft",
        required=True,
        readonly=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and (
                vals.get("state", "draft") != "draft"
                or vals.get("name") not in (None, False, _("New"))
                or vals.get("requested_by_id") not in (None, False, self.env.user.id)
                or any(
                    vals.get(field)
                    for field in (
                        "before_values",
                        "after_values",
                        "approved_by_id",
                        "approved_at",
                    )
                )
            ):
                raise UserError(_("Amendments must be approved through the apply action."))
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "hotel.reservation.amendment"
                    )
                    or _("New")
                )
        return super().create(vals_list)

    def _snapshot(self, reservation):
        return {
            "room_id": reservation.room_id.id or False,
            "room_type_id": reservation.room_type_id.id or False,
            "checkin_date": fields.Datetime.to_string(reservation.checkin_date),
            "checkout_date": fields.Datetime.to_string(reservation.checkout_date),
            "rate_night": reservation.rate_night,
            "amount_total": reservation.amount_total,
        }

    def _values_to_apply(self):
        self.ensure_one()
        values = {}
        if self.amendment_type == "room_move":
            if not self.new_room_id:
                raise UserError(_("Select the destination room."))
            values.update(
                {
                    "room_id": self.new_room_id.id,
                    "room_type_id": self.new_room_id.room_type_id.id,
                }
            )
        elif self.amendment_type in ("extend", "shorten", "late_checkout"):
            if not self.new_checkout_date:
                raise UserError(_("Enter the amended checkout time."))
            values["checkout_date"] = self.new_checkout_date
        elif self.amendment_type == "early_checkin":
            if not self.new_checkin_date:
                raise UserError(_("Enter the amended check-in time."))
            values["checkin_date"] = self.new_checkin_date
        elif self.amendment_type == "day_use":
            if not self.new_checkin_date or not self.new_checkout_date:
                raise UserError(_("Day use requires both check-in and checkout times."))
            values.update(
                {
                    "checkin_date": self.new_checkin_date,
                    "checkout_date": self.new_checkout_date,
                }
            )
        elif self.amendment_type == "reprice":
            if self.new_rate_night < 0:
                raise UserError(_("The amended rate cannot be negative."))
            values["rate_night"] = self.new_rate_night
            if "rate_locked" in self.reservation_id._fields:
                values["rate_locked"] = True
        return values

    def action_apply(self):
        for amendment in self:
            if amendment.state != "draft":
                raise UserError(_("This amendment has already been applied."))
            if not amendment.reason.strip():
                raise UserError(_("An amendment reason is required."))
            if amendment.reservation_id.state not in ("confirmed", "checked_in"):
                raise UserError(
                    _("Only confirmed or checked-in stays can be amended.")
                )
            is_manager = self.env.user.has_group("hotel_base.group_hotel_manager")
            is_supervisor = self.env.user.has_group(
                "hotel_base.group_hotel_fo_supervisor"
            )
            if amendment.amendment_type == "reprice" and not is_manager:
                raise UserError(_("Only a Hotel Manager can approve repricing."))
            if not is_supervisor and not is_manager:
                raise UserError(_("A Front Office Supervisor approval is required."))

            reservation = amendment.reservation_id
            old_room = reservation.room_id
            before = amendment._snapshot(reservation)
            values = amendment._values_to_apply()
            target_room = amendment.new_room_id or reservation.room_id
            new_checkin = values.get("checkin_date", reservation.checkin_date)
            new_checkout = values.get("checkout_date", reservation.checkout_date)
            if target_room:
                self.env["hotel.availability.service"].assert_room_available(
                    target_room,
                    new_checkin,
                    new_checkout,
                    exclude_reservation_id=reservation.id,
                )
            reservation._write_amendment_values(values)
            if amendment.amendment_type == "room_move" and reservation.state == "checked_in":
                old_room._set_stay_occupancy("checkout", hk_status="dirty")
                reservation.room_id._set_stay_occupancy("occupied")
            after = amendment._snapshot(reservation)
            amendment._write_applied_values(
                {
                    "before_values": before,
                    "after_values": after,
                    "approved_by_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                    "state": "applied",
                }
            )
            amendment._apply_financial_effects(before, after)
            reservation.message_post(
                body=_(
                    "Amendment %(amendment)s applied by %(user)s. Reason: %(reason)s",
                    amendment=amendment.name,
                    user=self.env.user.name,
                    reason=amendment.reason.strip(),
                )
            )
        return True

    def _apply_financial_effects(self, before, after):
        """Hook implemented by hotel_folio without reversing dependencies."""
        return None

    def _write_applied_values(self, values):
        return super(HotelReservationAmendment, self).write(values)

    def write(self, vals):
        action_fields = {
            "name",
            "requested_by_id",
            "state",
            "before_values",
            "after_values",
            "approved_by_id",
            "approved_at",
        }
        if action_fields.intersection(vals):
            raise UserError(_("Amendment approval fields can only be set by the apply action."))
        if self.filtered(lambda amendment: amendment.state == "applied"):
            raise UserError(_("Applied reservation amendments are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda amendment: amendment.state == "applied"):
            raise UserError(_("Applied reservation amendments cannot be deleted."))
        return super().unlink()


class HotelReservationGroup(models.Model):
    _name = "hotel.reservation.group"
    _description = "Hotel Group / Block Reservation"
    _inherit = ["mail.thread"]
    _order = "checkin_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    group_partner_id = fields.Many2one("res.partner", required=True, string="Group")
    agency_id = fields.Many2one(
        "res.partner", domain=[("is_hotel_agency", "=", True)]
    )
    billing_partner_id = fields.Many2one("res.partner", required=True)
    checkin_date = fields.Datetime(required=True)
    checkout_date = fields.Datetime(required=True)
    allocation_line_ids = fields.One2many(
        "hotel.reservation.group.allocation", "group_id", string="Requested Rooms"
    )
    member_ids = fields.One2many(
        "hotel.reservation", "group_id", string="Rooming List"
    )
    requested_room_count = fields.Integer(compute="_compute_counts")
    allocated_room_count = fields.Integer(compute="_compute_counts")
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled")],
        default="draft",
        readonly=True,
        required=True,
    )

    _group_date_check = models.Constraint(
        "CHECK (checkout_date > checkin_date)",
        "Group departure must be after arrival.",
    )

    @api.depends("allocation_line_ids.requested_qty", "member_ids")
    def _compute_counts(self):
        for group in self:
            group.requested_room_count = sum(
                group.allocation_line_ids.mapped("requested_qty")
            )
            group.allocated_room_count = len(group.member_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and (
                vals.get("state", "draft") != "draft"
                or vals.get("name") not in (None, False, _("New"))
            ):
                raise UserError(_("Group reservations must be confirmed through their action."))
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.reservation.group")
                    or _("New")
                )
        return super().create(vals_list)

    def action_allocate_available(self):
        for group in self:
            if group.state != "draft":
                raise UserError(_("Only draft groups can allocate rooms."))
            used_rooms = group.member_ids.mapped("room_id")
            for allocation in group.allocation_line_ids:
                existing = group.member_ids.filtered(
                    lambda member: member.room_type_id == allocation.room_type_id
                )
                needed = max(allocation.requested_qty - len(existing), 0)
                available = self.env["hotel.availability.service"].get_available_rooms(
                    group.property_id.id,
                    group.checkin_date,
                    group.checkout_date,
                    allocation.room_type_id.id,
                ) - used_rooms
                for room in available[:needed]:
                    member = self.env["hotel.reservation"].create(
                        {
                            "partner_id": group.group_partner_id.id,
                            "agency_id": group.agency_id.id,
                            "property_id": group.property_id.id,
                            "room_type_id": allocation.room_type_id.id,
                            "room_id": room.id,
                            "checkin_date": group.checkin_date,
                            "checkout_date": group.checkout_date,
                            "group_id": group.id,
                        }
                    )
                    used_rooms |= member.room_id
        return True

    def action_confirm(self):
        for group in self:
            allocated = group.member_ids.filtered("room_id")
            if not allocated:
                raise UserError(_("Allocate at least one room before confirmation."))
            for reservation in allocated.filtered(lambda member: member.state == "draft"):
                reservation.action_confirm()
            group._write_group_state("confirmed")
        return True

    def action_cancel(self):
        for group in self:
            for reservation in group.member_ids.filtered(
                lambda member: member.state in ("draft", "confirmed")
            ):
                reservation.action_cancel()
            group._write_group_state("cancelled")
        return True

    def _write_group_state(self, state):
        return super(HotelReservationGroup, self).write({"state": state})

    def write(self, vals):
        if "name" in vals:
            raise UserError(_("Group reservation references are assigned by the workflow."))
        if (
            "state" in vals
            and any(group.state != vals["state"] for group in self)
        ):
            raise UserError(
                _("Group reservation status can only be changed through its actions.")
            )
        protected = {
            "property_id",
            "group_partner_id",
            "agency_id",
            "billing_partner_id",
            "checkin_date",
            "checkout_date",
            "allocation_line_ids",
            "member_ids",
        }
        if (
            self.filtered(lambda group: group.state != "draft")
            and protected.intersection(vals)
        ):
            raise UserError(_("Confirmed or cancelled group reservations are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda group: group.state != "draft"):
            raise UserError(_("Only draft group reservations can be deleted."))
        return super().unlink()


class HotelReservationGroupAllocation(models.Model):
    _name = "hotel.reservation.group.allocation"
    _description = "Group Reservation Room-type Allocation"

    group_id = fields.Many2one(
        "hotel.reservation.group", required=True, ondelete="cascade", index=True
    )
    room_type_id = fields.Many2one("hotel.room.type", required=True)
    requested_qty = fields.Integer(required=True, default=1)

    _requested_qty_positive = models.Constraint(
        "CHECK (requested_qty > 0)", "Requested room quantity must be positive."
    )
    _group_room_type_uniq = models.Constraint(
        "unique (group_id, room_type_id)",
        "Each room type can appear only once on a group block.",
    )

    @api.constrains("group_id", "room_type_id")
    def _check_room_type_property(self):
        for allocation in self:
            if (
                allocation.room_type_id.property_id
                and allocation.room_type_id.property_id != allocation.group_id.property_id
            ):
                raise ValidationError(
                    _("The room type must be shared or belong to the group property.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        groups = self.env["hotel.reservation.group"].browse(
            [vals.get("group_id") for vals in vals_list if vals.get("group_id")]
        )
        if groups.filtered(lambda group: group.state != "draft"):
            raise UserError(_("Only draft group allocations can be changed."))
        return super().create(vals_list)

    def write(self, vals):
        if self.mapped("group_id").filtered(lambda group: group.state != "draft"):
            raise UserError(_("Only draft group allocations can be changed."))
        return super().write(vals)

    def unlink(self):
        if self.mapped("group_id").filtered(lambda group: group.state != "draft"):
            raise UserError(_("Only draft group allocations can be changed."))
        return super().unlink()
