release: python manage.py migrate --noinput
web: gunicorn config.wsgi --workers 3 --timeout 60 --log-file -
