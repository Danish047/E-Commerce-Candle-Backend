#!/usr/bin/env bash
# Build step for Render / Railway: install, collect static files, migrate, seed.
set -o errexit
pip install -r requirements.txt

# No SECRET_KEY env var? Generate one for this deploy so the public dev key is never used.
if [ -z "$SECRET_KEY" ] && [ ! -f .secret_key ]; then
  python -c "import secrets; print(secrets.token_urlsafe(50))" > .secret_key
fi

python manage.py collectstatic --noinput
python manage.py migrate --noinput

# Load the catalogue only when the store is empty, so admin edits are never overwritten.
if python manage.py shell -c "import sys; from catalog.models import Product; sys.exit(0 if Product.objects.exists() else 1)"; then
  echo "Catalogue already present - skipping seed."
else
  echo "Empty catalogue - seeding store data."
  if [ -n "$SEED_OWNER_EMAIL" ] && [ -n "$SEED_OWNER_PASSWORD" ]; then
    python manage.py seed_store --owner "$SEED_OWNER_EMAIL" --password "$SEED_OWNER_PASSWORD"
  else
    python manage.py seed_store
  fi
fi
