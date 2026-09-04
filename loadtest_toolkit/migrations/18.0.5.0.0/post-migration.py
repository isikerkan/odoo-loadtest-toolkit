# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

# generated records used to be linked through many2many relation tables;
# copy the links into the new loadtest_batch_id columns and drop the tables
MOVES = (
    ("loadtest_batch_partner_rel", "res_partner_id", "res_partner", "id"),
    ("loadtest_batch_order_rel", "sale_order_id", "sale_order", "id"),
    # products were linked as variants, the column now lives on the template
    ("loadtest_batch_product_rel", "product_product_id", "product_template", "variant"),
)


def migrate(cr, version):
    for rel_table, rel_column, table, mode in MOVES:
        cr.execute("SELECT to_regclass(%s)", (rel_table,))
        if cr.fetchone()[0] is None:
            continue
        if mode == "variant":
            cr.execute(
                f"""UPDATE {table} t SET loadtest_batch_id = r.loadtest_batch_id
                    FROM {rel_table} r JOIN product_product v ON v.id = r.{rel_column}
                    WHERE v.product_tmpl_id = t.id"""
            )
        else:
            cr.execute(
                f"""UPDATE {table} t SET loadtest_batch_id = r.loadtest_batch_id
                    FROM {rel_table} r WHERE r.{rel_column} = t.id"""
            )
        cr.execute(f"DROP TABLE {rel_table}")
