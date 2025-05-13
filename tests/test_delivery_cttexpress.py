# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
# Copyright 2022 Tecnativa - David Vidal
from odoo.exceptions import UserError
from odoo.tests import Form, common


class TestDeliveryCNEExpress(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shipping_product = cls.env["product.product"].create(
            {"type": "service", "name": "Test Shipping costs", "list_price": 10.0}
        )
        cls.carrier_yunexpress = cls.env["delivery.carrier"].create(
            {
                "name": "Yun Express",
                "delivery_type": "yunexpress",
                "product_id": cls.shipping_product.id,
                "debug_logging": True,
                "prod_environment": False,
                # CNE will maintain these credentials in order to allow OCA testing
                "yunexpress_user": "000002ODOO1",
                "yunexpress_password": "CAL%224271",
                "yunexpress_agency": "000002",
                "yunexpress_contract": "1",
                "yunexpress_customer": "ODOO1",
                "yunexpress_shipping_type": "19H",
            }
        )
        cls.product = cls.env["product.product"].create(
            {"type": "consu", "name": "Test product"}
        )
        cls.wh_partner = cls.env["res.partner"].create(
            {
                "name": "My Spanish WH",
                "city": "Zaragoza",
                "zip": "50001",
                "street": "C/ Mayor, 1",
                "country_id": cls.env.ref("base.es").id,
            }
        )
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Mr. Odoo & Co.",
                "city": "Madrid",
                "zip": "28001",
                "email": "odoo@test.com",
                "street": "Calle de La Rua, 3",
                "country_id": cls.env.ref("base.es").id,
            }
        )
        order_form = Form(cls.env["sale.order"].with_context(tracking_disable=True))
        order_form.partner_id = cls.partner
        with order_form.order_line.new() as line:
            line.product_id = cls.product
            line.product_uom_qty = 20.0
        cls.sale_order = order_form.save()
        cls.sale_order.carrier_id = cls.carrier_yunexpress
        cls.sale_order.action_confirm()
        # Ensure shipper address
        cls.sale_order.warehouse_id.partner_id = cls.wh_partner
        cls.picking = cls.sale_order.picking_ids
        cls.picking.move_ids.quantity_done = 20

    def test_00_yunexpress_test_connection(self):
        """Test credentials validation"""
        self.carrier_yunexpress.action_yun_validate_user()
        self.carrier_yunexpress.yunexpress_password = "Bad password"
        with self.assertRaises(UserError):
            self.carrier_yunexpress.action_yun_validate_user()

    def test_01_yunexpress_picking_confirm_simple(self):
        """The picking is confirm and the shipping is recorded to Yun Express"""
        self.picking.button_validate()
        self.assertTrue(self.picking.carrier_tracking_ref)
        self.picking.tracking_state_update()
        self.assertTrue(self.picking.tracking_state)
        self.picking.cancel_shipment()
        self.assertFalse(self.picking.carrier_tracking_ref)

    def test_02_yunexpress_picking_confirm_simple_pt(self):
        """We can deliver from Portugal as well"""
        self.wh_partner.country_id = self.env.ref("base.pt")
        self.picking.button_validate()
        self.assertTrue(self.picking.carrier_tracking_ref)

    def test_03_yunexpress_manifest(self):
        """API work although without data"""
        wizard = self.env["yunexpress.manifest.wizard"].create({})
        wizard.carrier_ids = self.carrier_yunexpress
        wizard.get_manifest()
        # There we have our manifest
        self.assertTrue(wizard.attachment_ids)

    def test_04_yunexpress_pickup(self):
        """API work although without data"""
        wizard = self.env["yunexpress.pickup.wizard"].create(
            {"carrier_id": self.carrier_yunexpress.id, "min_hour": 0.0}
        )
        wizard.create_pickup_request()
        # There we have our manifest
        self.assertTrue(wizard.code)
