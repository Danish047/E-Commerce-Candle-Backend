"""Load the demo catalog (same data the frontend mock used).

    python manage.py seed_store            # safe to re-run, updates by slug/code
    python manage.py seed_store --owner owner@lumiere.co.in --password Admin@123
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.models import User
from catalog.models import Category, Mood, Occasion, Product, Review
from core.models import QuizQuestion, StoreSettings
from orders.models import Coupon

DATA = Path(settings.BASE_DIR) / "seed_data"


def load(name):
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


class Command(BaseCommand):
    help = "Seed categories, products, reviews, coupons, quiz and store settings"

    def add_arguments(self, parser):
        parser.add_argument("--owner", help="Also create a store-owner login with this email")
        parser.add_argument("--password", default="ChangeMe@123")

    def handle(self, *args, **opts):
        StoreSettings.load()
        tax = load("taxonomy")
        for i, c in enumerate(tax["categories"]):
            Category.objects.update_or_create(slug=c["slug"], defaults={"name": c["name"], "description": c.get("description", ""), "sort_order": i})
        for model, key in ((Mood, "moods"), (Occasion, "occasions")):
            for i, x in enumerate(tax[key]):
                model.objects.update_or_create(slug=x["slug"], defaults={"name": x["name"], "sort_order": i})

        id_map = {}
        for p in load("products"):
            product, _ = Product.objects.update_or_create(
                slug=p["slug"],
                defaults={
                    k: p[k] for k in [
                        "name", "tagline", "description", "price", "compare_price", "size", "notes", "burn_time_hours",
                        "wax_type", "wick_type", "fragrance_load", "stock", "is_bestseller", "is_new", "color",
                    ]
                } | {"category": Category.objects.get(slug=p["category"]), "sku": f"LUM-{p['id']:03d}"},
            )
            product.moods.set(Mood.objects.filter(slug__in=p["moods"]))
            product.occasions.set(Occasion.objects.filter(slug__in=p["occasions"]))
            for i, url in enumerate(p.get("images") or []):
                product.photos.get_or_create(url=url, defaults={"sort_order": i})
            id_map[p["id"]] = product

        for r in load("reviews"):
            product = id_map.get(r["product_id"])
            if product and not Review.objects.filter(product=product, user_name=r["user_name"], comment=r["comment"]).exists():
                review = Review.objects.create(product=product, user_name=r["user_name"], rating=r["rating"], title=r.get("title", ""),
                                               comment=r["comment"], verified=r.get("verified", False))
                Review.objects.filter(pk=review.pk).update(created_at=f"{r['created_at']}T10:00:00Z")
        for p in id_map.values():
            p.refresh_rating()

        for c in load("coupons"):
            Coupon.objects.update_or_create(code=c["code"], defaults={
                "type": c["type"], "value": c["value"], "min_order": c["min_order"], "description": c["description"]})

        for i, q in enumerate(load("quiz")["questions"]):
            QuizQuestion.objects.update_or_create(key=q["id"], defaults={"question": q["question"], "options": q["options"], "sort_order": i})

        if opts.get("owner"):
            email = opts["owner"].lower()
            if not User.objects.filter(email=email).exists():
                User.objects.create_superuser(email=email, password=opts["password"], name="Store owner")
                self.stdout.write(self.style.SUCCESS(f"Owner login created: {email} / {opts['password']}"))
            else:
                self.stdout.write(f"Owner {email} already exists — password unchanged.")

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(id_map)} products, {Review.objects.count()} reviews, {Coupon.objects.count()} coupons."))
