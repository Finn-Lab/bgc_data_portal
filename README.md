DB to Django models
```
python manage.py inspectdb > api/models.py
```
- chanmges the AutoField to IntegerField
- add max_length to CharFields
- In contig.sequence change CharField to TextField
- Add primary_keys
- python manage.py makemigrations
- python manage.py migrate


Question to conclave
- How to have MultiChoiceCheckbox for API



requiements:
Biopython


---

## DB stats
A set of summary statistics can be computed, for the data in the database, which are then persisted back to the
database as a cache.

These are computed by a management command, which should be run after any data changes to the DB:

`python manage.py gather_latest_stats`