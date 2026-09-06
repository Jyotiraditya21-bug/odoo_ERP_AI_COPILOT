import os
from odoo.tools import convert_file


def post_init_hook(env):
    """Load demo data if not already present and apply environment demo passwords."""
    if not env["res.partner"].search([("name", "=", "ABC Industries")], limit=1):
        try:
            convert_file(
                env(context=dict(env.context, inventory_mode=True)),
                "ai_copilot",
                "demo/demo_data.xml",
                {},
                mode="init",
                noupdate=True,
                pathname="/mnt/extra-addons/ai_copilot/demo/demo_data.xml",
            )
        except Exception:
            pass

    credentials = {
        "sales.demo": os.environ.get("DEMO_SALESPERSON_PASSWORD"),
        "manager.demo": os.environ.get("DEMO_MANAGER_PASSWORD"),
    }
    for login, password in credentials.items():
        if password:
            user = env["res.users"].sudo().search([("login", "=", login)], limit=1)
            if user:
                user.write({"password": password})
