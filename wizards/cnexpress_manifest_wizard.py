# Copyright 2022 Tecnativa - David Vidal
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import base64

from odoo import fields, models


class CNEExpressManifestWizard(models.TransientModel):
    _name = "cnexpress.manifest.wizard"
    _description = "Get the CNE Express Manifest for the given date range"

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
        domain=[("delivery_type", "=", "cnexpress")],
        help="Leave empty to gather all the CNE account manifests",
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
        """List of shippings for the given dates as CNE provides them"""
        carriers = self.carrier_ids or self.env["delivery.carrier"].search(
            [("delivery_type", "=", "cnexpress")]
        )
        # Avoid getting repeated manifests. Carriers with different service
        # configuration would produce the same manifest.
        unique_accounts = {
            (c.cnexpress_customer, c.cnexpress_contract, c.cnexpress_agency)
            for c in carriers
        }
        filtered_carriers = self.env["delivery.carrier"]
        for customer, contract, agency in unique_accounts:
            filtered_carriers += fields.first(
                carriers.filtered(
                    lambda x: x.cnexpress_customer == customer
                    and x.cnexpress_contract == contract
                    and x.cnexpress_agency == agency
                )
            )
        for carrier in filtered_carriers:
            ctt_request = carrier._ctt_request()
            from_date = fields.Date.to_string(self.from_date)
            to_date = fields.Date.to_string(self.to_date)
            error, manifest = ctt_request.report_shipping(
                "ODOO", self.document_type, from_date, to_date
            )
            carrier._ctt_check_error(error)
            carrier._ctt_log_request(ctt_request)
            for _filename, file in manifest:
                filename = "{}{}{}-{}-{}.{}".format(
                    carrier.cnexpress_customer,
                    carrier.cnexpress_contract,
                    carrier.cnexpress_agency,
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
                "delivery_cnexpress.action_delivery_cnexpress_manifest_wizard"
            ),
            res_id=self.id,
        )
