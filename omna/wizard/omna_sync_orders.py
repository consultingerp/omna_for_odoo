# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timezone
from dateutil.parser import parse
from odoo import models, api, exceptions


_logger = logging.getLogger(__name__)


class OmnaSyncOrders(models.TransientModel):
    _name = 'omna.sync_orders_wizard'
    _inherit = 'omna.api'

    # @api.multi
    def sync_orders(self):
        try:
            limit = 100
            offset = 0
            requester = True
            orders = []
            while(requester):
                response = self.get('orders', {'limit': limit, 'offset': offset})
                data = response.get('data')
                orders.extend(data)
                if len(data) < limit:
                    requester = False
                else:
                    offset += limit

            for order in orders:
                act_order = self.env['sale.order'].search([('omna_id', '=', order.get('id'))])
                if act_order:
                    # Updating the order
                    data = {
                        'name': order.get('number'),
                        # 'state': order.get('status'), # Sincroniar esto con los state de sale.order
                    }
                    act_order.write(data)

                    # Updating las order lines
                    for line_item in order.get('line_items'):
                        act_orderline = self.env['sale.order.line'].search([('omna_id', '=', line_item.get('id'))])
                        product = self.env['product.product'].search([('default_code', '=', line_item.get('sku'))],
                                                                     limit=1)
                        if act_orderline:
                            data = {
                                'price_unit': line_item.get('price'),
                                'product_id': product.id if product else None,
                                'product_uom': product.product_tmpl_id.uom_id.id if product else None,
                                'product_uom_qty': line_item.get('quantity')
                            }
                            act_orderline.write(data)
                        else:
                            self._create_orderline(act_order, line_item, order.get('payments')[0].get('currency'))
                else:

                    partner_invoice = self.env['res.partner'].search([('name', '=', '%s %s' % (
                        order.get('bill_address').get('first_name'), order.get('bill_address').get('last_name')))],
                                                                     limit=1)
                    if not partner_invoice:
                        partner_invoice = self._create_partner(order.get('bill_address'))

                    partner_shipping = self.env['res.partner'].search([('name', '=', '%s %s' % (
                        order.get('ship_address').get('first_name'), order.get('ship_address').get('last_name')))],
                                                                      limit=1)
                    if not partner_shipping:
                        partner_shipping = self._create_partner(order.get('ship_address'))

                    if order.get('integration'):
                        integration = self.env['omna.integration'].search(
                            [('integration_id', '=', order.get('integration').get('id'))], limit=1)


                        if integration:
                            # Creating the order
                            data = {
                                'omna_id': order.get('id'),
                                'integration_id': integration.id,
                                'name': order.get('number'),
                                'origin': 'OMNA',
                                # 'state': order.get('status'),
                                'state': 'draft',
                                'date_order': parse(order.get('last_import_date').split('T')[0]),
                                'create_date': datetime.now(timezone.utc),
                                'partner_id': partner_invoice.id,
                                'partner_invoice_id': partner_invoice.id,
                                'partner_shipping_id': partner_shipping.id,
                                'pricelist_id': self.env['product.pricelist'].search(
                                    [('name', '=', 'Public Pricelist'), ('active', '=', True)], limit=1).id,

                            }
                            omna_order = self.env['sale.order'].create(data)

                            # Creating the orderlines
                            for line_item in order.get('line_items'):
                                self._create_orderline(omna_order, line_item, order.get('payments')[0].get('currency'))
        except Exception as e:
            _logger.error(e)
            raise exceptions.AccessError(e)


    def _create_partner(self, address):
        data = {
            'name': '%s %s' % (address.get('first_name'), address.get('last_name')),
            'type': 'contact',
            'street': ' '.join(address.get('address')),
            'city': address.get('city'),
            'zip': address.get('zip_code'),
        }
        country = self.env['res.country'].search([('code', '=', address.get('country'))], limit=1)
        if country:
            state_manager = self.env['res.country.state']
            data['country_id'] = country.id
            state = state_manager.search(
                [('code', '=', address.get('state')), ('country_id', '=', country.id)], limit=1)
            if state:
                data['state_id'] = state.id
        return self.env['res.partner'].create(data)


    def _create_orderline(self, omna_order, line_item, currency):
        currency = self.env['res.currency'].search([('name', '=', currency)], limit=1)
        if not currency:
            currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)

        product = self.env['product.product'].search([('default_code', '=', line_item.get('sku'))], limit=1)
        # Here ver el tema del currency
        data = {
            'order_id': omna_order.id,
            'omna_id': line_item.get('id'),
            'name': product.product_tmpl_id.name if product else line_item.get('name'),
            'price_unit': line_item.get('price'),
            'state': omna_order.state,
            'product_id': product.id if product else None,
            'product_uom': product.product_tmpl_id.uom_id.id if product else None,
            'product_uom_qty': line_item.get('quantity'),
            'customer_lead': 0,  #
            'currency_id': currency.id,
            'display_type': '' if product else 'line_section'
        }
        self.env['sale.order.line'].create(data)

