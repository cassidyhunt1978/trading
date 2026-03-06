# Celery worker module
from celery_worker.tasks import celery_app

# Export as 'app' for celery -A celery_worker.app
app = celery_app
