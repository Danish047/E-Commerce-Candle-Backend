#!/bin/bash
# Elastic Beanstalk runs this after each deploy (replaces Render's build.sh steps).
set -e
source /var/app/venv/*/bin/activate
cd /var/app/current
python manage.py collectstatic --noinput
python manage.py migrate --noinput
