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
        states={"draft": [("readonly", False)]},
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
        readonly=True,
        states={"draft": [("readonly", False)]},
    )
    amount = fields.Monetary(
        string="Monto",
        required=True,
        currency_field="currency_id",
        readonly=True,
        states={"draft": [("readonly", False)]},
    )
    note = fields.Text(
        string="Nota",
        readonly=True,
        states={"draft": [("readonly", False)]},
    )
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
            ("invoiced", "Facturado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        readonly=True,
        copy=False,
    )
    invoice_id = fields.Many2one(
        "account.move",
        string="Factura",
        readonly=True,
        copy=False,
    )
    invoice_count = fields.Integer(
        string="Cantidad de facturas",
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
            if record.state != "draft":
                continue
            if record.amount <= 0:
                raise UserError(_("El monto debe ser mayor a cero."))
            record.state = "confirmed"

    def action_reset_to_draft(self):
        for record in self:
            if record.state == "invoiced":
                raise UserError(_("No puede regresar a borrador un vale facturado."))
            record.state = "draft"

    def action_create_invoice(self):
        self.ensure_one()

        if self.state != "confirmed":
            raise UserError(_("Solo puede facturar vales confirmados."))
        if self.invoice_id:
            raise UserError(_("Este vale ya tiene una factura relacionada."))
        if self.amount <= 0:
            raise UserError(_("El monto debe ser mayor a cero."))

        journal = self.env["account.journal"].search([
            ("code", "=", "VALE"),
            ("type", "=", "sale"),
            ("company_id", "=", self.company_id.id),
        ], limit=1)

        if not journal:
            raise UserError(_("No se encontró un diario de ventas con código VALE para la compañía actual."))

        product = self.env["product.product"].search([
            ("default_code", "=", "VALE"),
        ], limit=1)

        if not product:
            raise UserError(_("No se encontró un producto con referencia interna VALE."))

        invoice = self.env["account.move"].with_company(self.company_id).create({
            "move_type": "out_invoice",
            "partner_id": self.partner_id.id,
            "invoice_date": self.date,
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "invoice_origin": self.name,
            "ref": self.name,
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": self.note or product.display_name or self.name,
                "quantity": 1.0,
                "price_unit": self.amount,
            })],
        })

        self.write({
            "invoice_id": invoice.id,
            "state": "invoiced",
        })

        return self.action_view_invoice()

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_("Este vale no tiene factura relacionada."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Factura"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.invoice_id.id,
            "target": "current",
        }
