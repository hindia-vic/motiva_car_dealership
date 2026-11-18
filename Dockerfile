# Development-only image. Production runs on Render via render.yaml (managed
# Postgres/Redis, object storage, Celery worker + beat). If you do build this
# image, pass the production environment at run time and run
# `python manage.py collectstatic --noinput` first; Whitenoise serves
# STATIC_ROOT and the manifest storage needs it populated.
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
