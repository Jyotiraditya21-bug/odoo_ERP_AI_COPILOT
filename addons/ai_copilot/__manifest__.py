{
    "name": "Secure Odoo AI Copilot",
    "version": "17.0.1.0.0",
    "summary": "Secure natural-language access to sales, inventory and company policy",
    "category": "Productivity",
    "author": "Portfolio Project",
    "license": "LGPL-3",
    "depends": ["base", "contacts", "sale_management", "stock"],
    "data": [
        "security/ai_copilot_security.xml",
        "security/ir.model.access.csv",
        "views/copilot_views.xml",
        "views/copilot_menus.xml",
    ],
    "demo": [],
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
