import os

from celery import Celery
from kombu import Queue

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bgc_data_portal.settings")

# app = Celery("config")
app = Celery("bgc_data_portal")

# pull in any config defined in Django settings, CELERY_*
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.update(
    broker_url=os.getenv("CELERY_BROKER_URL"),
    result_backend=os.getenv("CELERY_RESULT_BACKEND"),
)

# Queue declarations
app.conf.task_queues = [
    Queue("celery"),   # default
    Queue("scores"),   # dedicated queue for score recomputation
]

# auto-discover tasks.py in installed apps
app.autodiscover_tasks()
