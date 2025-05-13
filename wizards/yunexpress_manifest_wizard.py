# Copyright 2022 Tecnativa - David Vidal
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import base64

from odoo import fields, models


class CNEExpressManifestWizard(models.TransientModel):
    _name = "yunexpress.manifest.wizard"
    _description = "Get the Yun Express Manifest for the given date range"

    document_type = fields.Selection(
        selection=[("XLSX", "Excel"), ("PDF", "PDF")],
        string="Format",
        default="XLSX",
        required=True,
    )
    from_date = fields.Date(required=True, default=fields.Date.context_today)
    to_date = fields.Date(required=True, default=fields.Date.context_today)
    carrier_ids = fields.Many2many(
        string="Filter accounts",
        comodel_name="delivery.carrier",
        domain=[("delivery_type", "=", "yunexpress")],
        help="Leave empty to gather all the YUN account manifests",
    )
    state = fields.Selection(
        selection=[("new", "new"), ("done", "done")],
        default="new",
        readonly=True,
    )
    attachment_ids = fields.Many2many(
        comodel_name="ir.attachment", readonly=True, string="Manifests"
    )

    def get_manifest(self):
        """List of shippings for the given dates as YUN provides them"""
        carriers = self.carrier_ids or self.env["delivery.carrier"].search(
            [("delivery_type", "=", "yunexpress")]
        )
        # Avoid getting repeated manifests. Carriers with different service
        # configuration would produce the same manifest.
        unique_accounts = {
            (c.yunexpress_customer, c.yunexpress_contract, c.yunexpress_agency)
            for c in carriers
        }
        filtered_carriers = self.env["delivery.carrier"]
        for customer, contract, agency in unique_accounts:
            filtered_carriers += fields.first(
                carriers.filtered(
                    lambda x: x.yunexpress_customer == customer
                    and x.yunexpress_contract == contract
                    and x.yunexpress_agency == agency
                )
            )
        for carrier in filtered_carriers:
            yun_request = carrier._yun_request()
            from_date = fields.Date.to_string(self.from_date)
            to_date = fields.Date.to_string(self.to_date)
            error, manifest = yun_request.report_shipping(
                "ODOO", self.document_type, from_date, to_date
            )
            carrier._yun_check_error(error)
            carrier._yun_log_request(yun_request)
            for _filename, file in manifest:
                filename = "{}{}{}-{}-{}.{}".format(
                    carrier.yunexpress_customer,
                    carrier.yunexpress_contract,
                    carrier.yunexpress_agency,
                    from_date.replace("-", ""),
                    to_date.replace("-", ""),
                    self.document_type.lower(),
                )
                self.attachment_ids += self.env["ir.attachment"].create(
                    {
                        "datas": base64.b64encode(file),
                        "name": filename,
                        "res_model": self._name,
                        "res_id": self.id,
                        "type": "binary",
                    }
                )
        self.state = "done"
        return dict(
            self.env["ir.actions.act_window"]._for_xml_id(
                "delivery_yunexpress.action_delivery_yunexpress_manifest_wizard"
            ),
            res_id=self.id,
        )
