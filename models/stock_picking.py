# Copyright 2022 Tecnativa - David Vidal
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import _, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def yunexpress_get_label(self):
        """Get label for current picking

        :return tuple: (filename, filecontent)
        """
        self.ensure_one()
        tracking_ref = self.carrier_tracking_ref
        if self.delivery_type != "yunexpress" or not tracking_ref:
            return
        label = self.carrier_id.yunexpress_get_label(tracking_ref)
        self.message_post(
            body=(_("Yun Express label for %s") % tracking_ref),
            attachments=label,
        )
        return label
