"""Convert ``BgcDomain.go_slim`` from a single string to a list of slim terms.

A domain can now legitimately fold down to multiple GO-slim names — the
input is the union of slim ancestors across every GO term InterProScan
attached to the signature (see ``discovery.services.go_slim``). Storing
one name was a Pfam-era simplification.

Old rows ingested under the previous schema carried a single capitalised
molecular_function term in ``go_slim``. The PostgreSQL ``USING`` clause
wraps each non-empty value in a one-element JSONB array so the column
type can be flipped without losing information. A full refresh of the
slim names against the new ``go_slim_map.json`` should be run afterwards
via ``manage.py backfill_go_slim``.
"""

from django.db import migrations, models


FORWARD_SQL = """
ALTER TABLE discovery_bgc_domain
    ALTER COLUMN go_slim DROP DEFAULT,
    ALTER COLUMN go_slim TYPE jsonb
        USING CASE
            WHEN go_slim IS NULL OR go_slim = '' THEN '[]'::jsonb
            ELSE jsonb_build_array(go_slim)
        END,
    ALTER COLUMN go_slim SET DEFAULT '[]'::jsonb,
    ALTER COLUMN go_slim SET NOT NULL;
"""

REVERSE_SQL = """
ALTER TABLE discovery_bgc_domain
    ALTER COLUMN go_slim DROP DEFAULT,
    ALTER COLUMN go_slim TYPE varchar(100)
        USING COALESCE(go_slim ->> 0, ''),
    ALTER COLUMN go_slim SET DEFAULT '',
    ALTER COLUMN go_slim SET NOT NULL;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("discovery", "0024_cds_chemont"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="bgcdomain",
                    name="go_slim",
                    field=models.JSONField(blank=True, default=list),
                ),
            ],
        ),
    ]
