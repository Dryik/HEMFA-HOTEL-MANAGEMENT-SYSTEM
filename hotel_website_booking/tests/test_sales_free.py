import ast
from pathlib import Path

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelWebsiteSalesFree(TransactionCase):
    def test_addon_has_no_sales_dependency_or_order_model(self):
        addon = Path(__file__).resolve().parents[1]
        manifest = ast.literal_eval(
            (addon / "__manifest__.py").read_text(encoding="utf-8")
        )
        self.assertFalse(
            {"sale", "sale_management", "website_sale"}.intersection(
                manifest["depends"]
            )
        )
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in addon.rglob("*")
            if path.suffix in {".py", ".xml", ".js"}
            and "tests" not in path.parts
        ).lower()
        self.assertNotIn("sale.order", source)
