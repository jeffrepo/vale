from odoo import api, fields, models, _
from odoo.exceptions import UserError


class Vale(models.Model):
    _name = "vale.vale"
    _description = "Vale"
    _order = "id desc"

    name = fields.Char(
        string="Secuencia interna",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("Nuevo"),
    )
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        readonly=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Usuario creación",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Socio",
        required=True,
    )
    amount = fields.Monetary(
        string="Monto",
        required=True,
        currency_field="currency_id",
    )
    note = fields.Text(string="Nota")
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("confirmed", "Confirmado"),
            ("statement", "Estado de cuenta"),
            ("cancelled", "Anulado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        readonly=True,
        copy=False,
    )
    invoice_id = fields.Many2one(
        "account.move",
        string="Estado de cuenta",
        readonly=True,
        copy=False,
    )
    invoice_count = fields.Integer(
        string="Cantidad de estados de cuenta",
        compute="_compute_invoice_count",
    )

    @api.depends("invoice_id")
    def _compute_invoice_count(self):
        for record in self:
            record.invoice_count = 1 if record.invoice_id else 0

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = sequence.next_by_code("vale.vale") or _("Nuevo")
            if not vals.get("company_id"):
                vals["company_id"] = self.env.company.id
        return super().create(vals_list)

    def write(self, vals):
        protected_fields = {
            "date",
            "partner_id",
            "amount",
            "note",
            "company_id",
            "currency_id",
            "user_id",
        }
        for record in self:
            if record.state != "draft" and protected_fields.intersection(vals):
                raise UserError(_("Solo puede modificar los datos del vale cuando está en borrador."))
        return super().write(vals)

    def unlink(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Solo puede eliminar vales en estado borrador."))
        return super().unlink()

    def action_confirm(self):
        for record in self:
            if record.state == "draft":
                if record.amount <= 0:
                    raise UserError(_("El monto debe ser mayor a cero."))
                record.state = "confirmed"

    def action_cancel(self):
        for record in self:
            if record.state == "statement":
                raise UserError(_("No puede anular un vale que ya tiene estado de cuenta generado."))
            record.state = "cancelled"

    def action_reset_to_draft(self):
        for record in self:
            if record.state == "statement":
                raise UserError(_("No puede regresar a borrador un vale con estado de cuenta generado."))
            record.state = "draft"

    def _get_statement_journal(self):
        journal = self.env["account.journal"].search([
            ("code", "=", "VALE"),
            ("type", "=", "sale"),
            ("company_id", "=", self.company_id.id),
        ], limit=1)
        if not journal:
            raise UserError(_("No se encontró un diario de ventas con código VALE para la compañía actual."))
        return journal

    def _get_product_by_default_code(self, default_code, error_message):
        product = self.env["product.product"].search([
            ("default_code", "=", default_code),
        ], limit=1)
        if not product:
            raise UserError(error_message)
        return product

    def action_generate_statement(self):
        for record in self:
            if record.state != "confirmed":
                raise UserError(_("Solo puede generar estado de cuenta para vales confirmados."))
            if record.invoice_id:
                raise UserError(_("El vale %s ya tiene estado de cuenta relacionado.") % record.name)
            if record.amount <= 0:
                raise UserError(_("El monto del vale %s debe ser mayor a cero.") % record.name)

        created_invoice_ids = []

        for record in self:
            journal = record._get_statement_journal()
            product_cad = record._get_product_by_default_code(
                "CAD",
                _("No se encontró un producto con referencia interna CAD."),
            )
            product_rec = record._get_product_by_default_code(
                "REC",
                _("No se encontró un producto con referencia interna REC."),
            )
            rec_amount = record.amount * 0.05

            invoice = self.env["account.move"].with_company(record.company_id).create({
                "move_type": "out_invoice",
                "partner_id": record.partner_id.id,
                "invoice_date": record.date,
                "fecha_estado_cuenta": record.date,
                "journal_id": journal.id,
                "company_id": record.company_id.id,
                "invoice_origin": record.name,
                "ref": record.name,
                "invoice_line_ids": [
                    (0, 0, {
                        "product_id": product_cad.id,
                        "name": product_cad.display_name or record.name,
                        "quantity": 1.0,
                        "price_unit": record.amount,
                    }),
                    (0, 0, {
                        "product_id": product_rec.id,
                        "name": product_rec.display_name or _("Recargo 5%%"),
                        "quantity": 1.0,
                        "price_unit": rec_amount,
                    }),
                ],
            })
            record.write({
                "invoice_id": invoice.id,
                "state": "statement",
            })
            created_invoice_ids.append(invoice.id)

        if len(created_invoice_ids) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": _("Estado de cuenta"),
                "res_model": "account.move",
                "view_mode": "form",
                "res_id": created_invoice_ids[0],
                "target": "current",
            }

        return {
            "type": "ir.actions.act_window",
            "name": _("Estados de cuenta"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", created_invoice_ids)],
            "target": "current",
            "context": {"create": False},
        }

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_("Este vale no tiene estado de cuenta relacionado."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Estado de cuenta"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.invoice_id.id,
            "target": "current",
        }
