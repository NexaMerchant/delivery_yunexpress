from odoo import api, fields, models


class CNEExpressPickupWizard(models.TransientModel):
    _name = "yunexpress.pickup.wizard"
    _description = "Generate shipping pickups"

    carrier_id = fields.Many2one(
        comodel_name="delivery.carrier",
        domain=[("delivery_type", "=", "yunexpress")],
    )
    shipping_code = fields.Char(
        string="Shipping Code",
        help="Shipping code to be used for the pickup request",
        required=True,
    )
    # delivery_date = fields.Date(required=True, default=fields.Date.context_today)
    # min_hour = fields.Float(required=True)
    # max_hour = fields.Float(required=True, default=23.99)
    code = fields.Char(readonly=True)
    state = fields.Selection(
        selection=[("new", "new"), ("done", "done")],
        default="new",
        readonly=True,
    )

    @api.onchange("min_hour", "max_hour")
    def _onchange_hours(self):
        """Min and max hours UX"""
        # Avoid negative or after midnight
        self.min_hour = min(self.min_hour, 23.99)
        self.min_hour = max(self.min_hour, 0.0)
        self.max_hour = min(self.max_hour, 23.99)
        self.max_hour = max(self.max_hour, 0.0)
        # Avoid wrong order
        self.max_hour = max(self.max_hour, self.min_hour)

    def create_pickup_request(self):
        """Get the pickup code"""

        def convert_float_time_to_str(float_time):
            """Helper to pass the times in the expexted format 'HH:MM'"""
            return "{:02.0f}:{:02.0f}".format(*divmod(float_time * 60, 60))

        yun_request = self.carrier_id._yun_request()
        # delivery_date = fields.Date.to_string(self.delivery_date)
        shipping_code = self.shipping_code
        error, code = yun_request.create_request(
            shipping_code,
        )
        self.carrier_id._yun_check_error(error)
        self.carrier_id._yun_log_request(yun_request)
        self.code = code
        self.state = "done"
        return dict(
            self.env["ir.actions.act_window"]._for_xml_id(
                "delivery_yunexpress.action_delivery_yunexpress_pickup_wizard"
            ),
            res_id=self.id,
        )
