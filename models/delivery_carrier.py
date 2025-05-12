from odoo import _, api, fields, models
from odoo.exceptions import UserError
import logging
from odoo.tools.config import config
from odoo import http
import requests
import base64

_logger = logging.getLogger(__name__)

from .yunexpress_request import YUNExpressRequest


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(
        selection_add=[("yunexpress", "Yun Express")],
        ondelete={"yunexpress": "set default"},
    )
    yunexpress_api_cid = fields.Char(
        string="API Client ID",
        help="Yun Express API Client ID. This is the user used to connect to the API.",
    )
    yunexpress_api_secret = fields.Char(
        string="API Secret",
        help="Yun Express API Secret. This is the password used to connect to the API.",
    )

    yunexpress_document_model_code = fields.Selection(
        selection=[
            ("SINGLE", "Single"),
            ("MULTI1", "Multi 1"),
            ("MULTI3", "Multi 3"),
            ("MULTI4", "Multi 4"),
        ],
        default="SINGLE",
        string="Document model",
    )
    yunexpress_document_format = fields.Selection(
        selection=[("PDF", "PDF"), ("PNG", "PNG"), ("BMP", "BMP")],
        default="PDF",
        string="Document format",
    )
    yunexpress_document_offset = fields.Integer(string="Document Offset")

    @api.onchange("delivery_type")
    def _onchange_delivery_type_ctt(self):
        """Default price method for CNE as the API can't gather prices."""
        if self.delivery_type == "yunexpress":
            self.price_method = "base_on_rule"

    def _ctt_request(self):
        """Get CNE Request object

        :return YUNExpressRequest: Yun Express Request object
        """
        _logger.debug("yunexpress_api_cid: %s", self.yunexpress_api_cid)
        if not self.yunexpress_api_cid:
            _logger.warning("yunexpress_api_cid is False, please check configuration.")
        record_values = self.read()[0]
        _logger.debug("yunexpress_api_secret: %s", record_values["yunexpress_api_secret"])
        if self.yunexpress_api_secret is False:
            # read the value from the configuration
            _logger.warning("yunexpress_api_secret is False, please check configuration.")
            self.yunexpress_api_secret = config.get(
                "cne_api_secret", self.yunexpress_api_secret
            )
        if self.yunexpress_api_cid is False:
            self.yunexpress_api_cid = config.get(
                "cne_api_cid", self.yunexpress_api_cid
            )
        

        return YUNExpressRequest(
            api_cid=self.yunexpress_api_cid,
            api_token=self.yunexpress_api_secret,
            prod=self.prod_environment,
        )

    @api.model
    def _ctt_log_request(self, ctt_request):
        """When debug is active requests/responses will be logged in ir.logging

        :param ctt_request ctt_request: Yun Express request object
        """
        self.log_xml(ctt_request.ctt_last_request, "ctt_request")
        self.log_xml(ctt_request.ctt_last_response, "ctt_response")

    def _ctt_check_error(self, error):
        """Common error checking. We stop the program when an error is returned.

        :param list error: List of tuples in the form of (code, description)
        :raises UserError: Prompt the error to the user
        """
        print(error)
        return

        if not error:
            return
        error_msg = ""
        for code, msg in error:
            if not code:
                continue
            error_msg += "{} - {}\n".format(code, msg)
        if not error_msg:
            return
        raise UserError(_("Yun Express Error:\n\n%s") % error_msg)

    @api.model
    def _yunexpress_format_tracking(self, tracking):
        """Helper to forma tracking history strings

        :param OrderedDict tracking: CNE tracking values
        :return str: Tracking line
        """
        status = "{} - [{}] {}".format(
            fields.Datetime.to_string(tracking["StatusDateTime"]),
            tracking["StatusCode"],
            tracking["StatusDescription"],
        )
        if tracking["IncidentCode"]:
            status += " ({}) - {}".format(
                tracking["IncidentCode"], tracking["IncidentDescription"]
            )
        return status

    @api.onchange("yunexpress_shipping_type")
    def _onchange_yunexpress_shipping_type(self):
        """Control service validity according to credentials

        :raises UserError: We list the available services for given credentials
        """
        if not self.yunexpress_shipping_type:
            return
        # Avoid checking if credentianls aren't setup or are invalid
        ctt_request = self._ctt_request()
        error, service_types = ctt_request.get_service_types()
        self._ctt_log_request(ctt_request)
        self._ctt_check_error(error)
        type_codes, type_descriptions = zip(*service_types)
        if self.yunexpress_shipping_type not in type_codes:
            service_name = dict(
                self._fields["yunexpress_shipping_type"]._description_selection(
                    self.env
                )
            )[self.yunexpress_shipping_type]
            raise UserError(
                _(
                    "This Yun Express service (%(service_name)s) isn't allowed for "
                    "this account configuration. Please choose one of the followings\n"
                    "%(type_descriptions)s",
                    service_name=service_name,
                    type_descriptions=type_descriptions,
                )
            )

    def action_ctt_validate_user(self):
        """Maps to API's ValidateUser method

        :raises UserError: If the user credentials aren't valid
        """
        self.ensure_one()
        ctt_request = self._ctt_request()
        error = ctt_request.validate_user()
        self._ctt_log_request(ctt_request)

    def _prepare_yunexpress_shipping(self, picking):
        """Convert picking values for Yun Express API

        :param record picking: `stock.picking` record
        :return dict: Values prepared for the CNE connector
        """
        self.ensure_one()
        # A picking can be delivered from any warehouse
        sender_partner = picking.company_id.partner_id
        if picking.picking_type_id:
            sender_partner = (
                picking.picking_type_id.warehouse_id.partner_id
                or picking.company_id.partner_id
            )
        recipient = picking.partner_id
        recipient_entity = picking.partner_id.commercial_partner_id
        weight = picking.shipping_weight
        reference = picking.name
        if picking.sale_id:
            reference = "{}-{}".format(picking.sale_id.name, reference)

        # https://apifox.com/apidoc/shared/6eba6d59-905d-4587-810b-607358a30aa3/doc-2909525

        goodslist = []
        # Get the product name and quantity from the picking
        for move in picking.move_ids:
            # get the product name and quantity from the picking
            # get the product declared_name_cn and declared_name_en, declared_price
            # if the move.product_id.declared_price is 0.0 and product type is service, skip the product
            if move.product_id.declared_price == 0.0 and move.product_id.type == "service":
                continue
            goodslist.append(
                {
                    "cxGoods": move.product_id.declared_name_en,
                    "cxGoodsA": move.product_id.declared_name_cn,
                    "fxPrice": move.product_id.declared_price,
                    "cxMoney": picking.company_id.currency_id.name,
                    "ixQuantity": 1,
                }
            )

        # labelContent
        labelcontent = {
            "fileType": "PDF",
            "labelType": "label10x15",
            "pickList": 1
        }

        vatCode = None;
        iossCode = None;

        # if recipient.country_id.code == "UK":
        vatCode = config.get("yunexpress_eu_vat_code", vatCode)
        
        #if recipient.country_id.code == "DE":
        # europe need to set the vatcode and ioss code
        # vatCode = config.get("yunexpress_eu_vat_code", vatCode)
        # iossCode = config.get("yunexpress_eu_ioss_code", iossCode)
        # else:
        # vatCode = config.get("yunexpress_eu_vat_code", vatCode)
        # iossCode = config.get("yunexpress_eu_ioss_code", iossCode)
        iossCode = config.get("yunexpress_eu_ioss_code", iossCode)

        return {
            "cEmsKind": self.name.replace(" ",""),  # Optional
            "nItemType": 1,  # Optional
            "cAddrFrom": "MYSHOP",
            "iItem": 1,  # Optional
            # order number
            "cRNo": reference,
            # order receiver country code
            "cDes": recipient.country_id.code,
            # order receiver name
            "cReceiver": recipient.name or recipient_entity.name,
            # order receiver company name
            "cRunit": recipient_entity.name,
            # order receiver address
            "cRAddr": recipient.street,
            # order receiver city
            "cRCity": recipient.city,
            # order receiver province
            "cRProvince": recipient.state_id.name,
            # order receiver postal code
            "cRPostcode": recipient.zip,
            # order receiver country name
            "cRCountry": recipient.country_id.name,
            # order receiver phone number
            "cRPhone": str(recipient.phone or recipient_entity.phone or ''),
            # order receiver mobile number
            "cRSms": str(recipient.mobile or recipient_entity.mobile or ''),
            # order receiver email address
            "cRPhone": str(recipient.phone or recipient_entity.phone or ''),
            # order package weight
            "fWeight": 1,  # Weight in grams
            # order memo
            "cMemo": None,  # Optional
            # order reserve
            "cReserve": None,  # Optional
            # order vat code
            "vatCode": vatCode,  # Optional
            # order ioss code
            "iossCode": iossCode,  # Optional
            # order sender name
            "cSender": sender_partner.name,
            "labelContent": labelcontent,  # Optional
            "GoodsList": goodslist
        }

    def yunexpress_send_shipping(self, pickings):
        """Yun Express wildcard method called when a picking is confirmed

        :param record pickings: `stock.picking` recordset
        :raises UserError: On any API error
        :return dict: With tracking number and delivery price (always 0)
        """
        print("yunexpress_send_shipping")
        ctt_request = self._ctt_request()
        print("yunexpress_send_shipping ctt_request")
        print(self.yunexpress_api_cid)
        print(ctt_request.ctt_last_request)
        print("yunexpress_send_shipping ctt_request")
        result = []
        for picking in pickings:

            # Check if the picking is already shipped
            if picking.state == "done":
                raise UserError(_("This picking is already shipped."))
            
            # check if the picking has a tracking number and the same carrier
            if picking.carrier_tracking_ref and picking.carrier_id == self:
                raise UserError(_("This picking already has a tracking number."))

            vals = self._prepare_yunexpress_shipping(picking)

            print(vals)
        
            try:
                error, documents, tracking = ctt_request.manifest_shipping(pickings=picking,shipping_values=vals)
                self._ctt_check_error(error)
            except Exception as e:
                raise (e)
            finally:
                self._ctt_log_request(ctt_request)

            vals.update({"tracking_number": tracking, "exact_price": 0})
            vals.update({"carrier_tracking_ref": tracking})
            # save the tracking number to carrier_tracking_ref field
            picking.carrier_tracking_ref = tracking

            # save the tracking number to carrier_tracking_ref field
            picking.carrier_tracking_ref = tracking
            picking.update({"carrier_tracking_ref": tracking})

            # Download the PDF document from the URL
            response = requests.get(documents)
            if response.status_code != 200:
                raise Exception("Error in request")
            pdf_content = response.content
            
            attachment = self.env['ir.attachment'].create({
                'name': tracking + '.pdf',
                'datas': base64.b64encode(pdf_content),
                'db_datas': base64.b64encode(pdf_content),
                'res_model': 'stock.picking',  # Attach to the stock.picking
                'res_id': pickings.id,  # Attach to the current picking
                'type': 'binary',
                'mimetype': 'application/pdf',
                'url': documents,
            })


            # The default shipping method doesn't allow to configure the label
            # format, so once we get the tracking, we ask for it again.
            #documents = self.yunexpress_get_label(tracking)
            # We post an extra message in the chatter with the barcode and the
            # label because there's clean way to override the one sent by core.
            body = _("CNE Shipping Documents")
            picking.message_post(body=body, attachments=attachment)
            # the documents is a url, we need to redirect to the url to print the label

            # update the sale order picking state to "sent"
            # if picking.sale_id and picking.sale_id.state == "sale":
            #     picking.sale_id.state = "sent"
            # updte the sale order delivery date to now
            picking.sale_id.shipping_time = fields.Datetime.now()

            result.append(vals)
        return result

    def yunexpress_cancel_shipment(self, pickings):
        """Cancel the expedition

        :param recordset: pickings `stock.picking` recordset
        :returns boolean: True if success
        """
        ctt_request = self._ctt_request()
        for picking in pickings.filtered("carrier_tracking_ref"):
            try:
                error = ctt_request.cancel_shipping(picking.carrier_tracking_ref)
                self._ctt_check_error(error)
            except Exception as e:
                raise (e)
            finally:
                self._ctt_log_request(ctt_request)
        return True

    def yunexpress_get_label(self, reference):
        """Generate label for picking

        :param str reference: shipping reference
        :returns tuple: (file_content, file_name)
        """
        if not self:
            return False
        if not reference:
            return False
        self.ensure_one()
        ctt_request = self._ctt_request()
        try:
            error, label = ctt_request.get_documents_multi(
                reference,
                model_code=self.yunexpress_document_model_code,
                kind_code=self.yunexpress_document_format,
                offset=self.yunexpress_document_offset,
            )
            self._ctt_check_error(error)
        except Exception as e:
            raise (e)
        finally:
            self._ctt_log_request(ctt_request)
        if not label:
            return False
        return label

    def yunexpress_tracking_state_update(self, picking):
        """Wildcard method for Yun Express tracking followup

        :param recod picking: `stock.picking` record
        """
        self.ensure_one()
        if not picking.carrier_tracking_ref:
            return
        ctt_request = self._ctt_request()
        try:
            error, trackings = ctt_request.get_tracking(picking.carrier_tracking_ref)
            self._ctt_check_error(error)
        except Exception as e:
            raise (e)
        finally:
            self._ctt_log_request(ctt_request)
        picking.tracking_state_history = "\n".join(
            [self._yunexpress_format_tracking(tracking) for tracking in trackings]
        )
        current_tracking = trackings.pop()
        picking.tracking_state = self._yunexpress_format_tracking(current_tracking)
        picking.delivery_state = YUNEXPRESS_DELIVERY_STATES_STATIC.get(
            current_tracking["StatusCode"], "incidence"
        )

    def yunexpress_get_tracking_link(self, picking):
        """Wildcard method for Yun Express tracking link.

        :param record picking: `stock.picking` record
        :return str: tracking url
        """
        tracking_url = (
            "https://t.17track.net/en#nums={}"
        )
        return tracking_url.format(picking.carrier_tracking_ref)
