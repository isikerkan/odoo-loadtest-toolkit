# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "Load Test Toolkit",
    "summary": "Generate load-test users and data batches, with guarded cleanup",
    "version": "18.0.2.0.1",
    "category": "Extra Tools",
    "website": "https://github.com/sverkanisik/odoo-loadtest-toolkit",
    "author": "isikerkan, sverkanisik",
    "license": "AGPL-3",
    "application": True,
    "installable": True,
    "depends": ["sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/loadtest_batch_views.xml",
    ],
}
