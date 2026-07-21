from datetime import timedelta


def migrate_legacy_rates(env):
    """Preserve legacy rule ownership and confirmed prices during upgrade."""
    rule_model = env["hotel.rate.rule"].sudo()
    plan_model = env["hotel.seasonal.pricing"].sudo()
    for property_rec in env["hotel.property"].sudo().search([]):
        legacy_rules = rule_model.search(
            [
                ("property_id", "=", property_rec.id),
                ("seasonal_pricing_id", "=", False),
            ]
        )
        if legacy_rules:
            plan = plan_model.search(
                [
                    ("property_id", "=", property_rec.id),
                    ("name", "=", "Legacy Rates"),
                ],
                limit=1,
            )
            if not plan:
                plan = plan_model.create(
                    {
                        "name": "Legacy Rates",
                        "property_id": property_rec.id,
                        "date_start": min(legacy_rules.mapped("date_start")),
                        "date_end": max(legacy_rules.mapped("date_end")),
                        "description": "Automatically migrated nightly rate rules.",
                    }
                )
            legacy_rules.write({"seasonal_pricing_id": plan.id})
            if plan.state == "draft":
                plan.action_activate()

    reservations = env["hotel.reservation"].sudo().search(
        [
            ("state", "!=", "draft"),
            ("rate_line_ids", "=", False),
            ("room_type_id", "!=", False),
        ]
    )
    rate_line_model = env["hotel.reservation.rate.line"].sudo()
    for reservation in reservations:
        business_date = reservation.property_id.get_business_date(
            reservation.checkin_date
        )
        departure_date = reservation.property_id.get_business_date(
            reservation.checkout_date
        )
        if departure_date <= business_date:
            departure_date = business_date + timedelta(days=1)
        while business_date < departure_date:
            rate_line_model.create(
                {
                    "reservation_id": reservation.id,
                    "business_date": business_date,
                    "currency_id": reservation.currency_id.id,
                    "base_amount": reservation.rate_night,
                    "occupancy_multiplier": 1.0,
                    "room_amount": reservation.rate_night,
                    "supplement_amount": 0.0,
                    "tax_amount": 0.0,
                    "amount_untaxed": reservation.rate_night,
                    "amount_total": reservation.rate_night,
                    "posted": True,
                    "legacy_snapshot": True,
                }
            )
            business_date += timedelta(days=1)
        reservation.with_context(hotel_migration=True).write({"rate_locked": True})


def post_init_hook(env):
    migrate_legacy_rates(env)
