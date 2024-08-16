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