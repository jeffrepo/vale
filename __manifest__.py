{
    "name": "Vale",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "summary": "Gestión de vales por monto",
    "description": "Aplicación para crear, confirmar, facturar e imprimir vales por monto.",
    "author": "Jefferson Silva",
    "depends": ["base", "account", "product"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/vale_views.xml",
        "report/vale_report.xml",
    ],
    "application": True,
    "installable": True,
    "license": "LGPL-3",
}
