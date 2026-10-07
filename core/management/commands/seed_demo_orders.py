"""Fill the admin dashboard with realistic sample customers and orders.
Only for local demos — never run this on the live store.

    python manage.py seed_demo_orders --count 80
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F
from django.utils import timezone

from accounts.models import User
from catalog.models import Product
from core.models import ContactMessage, NewsletterSubscriber
from orders.models import Coupon, Order, OrderEvent, OrderItem

NAMES = ["Aarav Shah", "Diya Patel", "Kabir Mehta", "Ishita Rao", "Vihaan Gupta", "Meera Iyer", "Arjun Nair",
         "Saanvi Joshi", "Rohan Das", "Ananya Kulkarni", "Neha Verma", "Kunal Bose", "Tara Menon", "Dev Malhotra"]
CITIES = [("Indore", "Madhya Pradesh", "452001"), ("Mumbai", "Maharashtra", "400050"), ("Bengaluru", "Karnataka", "560034"),
          ("Delhi", "Delhi", "110017"), ("Pune", "Maharashtra", "411001"), ("Jabalpur", "Madhya Pradesh", "482001"),
          ("Kolkata", "West Bengal", "700019"), ("Chennai", "Tamil Nadu", "600040")]


class Command(BaseCommand):
    help = "Create sample customers, orders, messages and subscribers for demos"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=80)
        parser.add_argument("--days", type=int, default=60)

    def handle(self, *args, count, days, **opts):
        products = list(Product.objects.filter(is_active=True))
        if not products:
            raise CommandError("Run `python manage.py seed_store` first.")
        rnd = random.Random(7)
        customers = []
        for n in NAMES:
            email = n.lower().replace(" ", ".") + "@example.com"
            u, created = User.objects.get_or_create(email=email, defaults={"name": n, "phone": f"98{rnd.randint(10000000, 99999999)}"})
            if created:
                u.set_password("demo12345")
                u.date_joined = timezone.now() - timedelta(days=rnd.randint(0, days))
                u.save()
            customers.append(u)
        coupons = list(Coupon.objects.all())
        now = timezone.now()

        for _ in range(count):
            user = rnd.choice(customers + [None, None])
            name = user.name if user else rnd.choice(NAMES)
            city, state, pin = rnd.choice(CITIES)
            picks = rnd.sample(products, rnd.choice([1, 1, 1, 2, 2, 3]))
            lines = [(p, rnd.choice([1, 1, 2, 3])) for p in picks]
            subtotal = sum(p.price * q for p, q in lines)
            coupon = rnd.choice(coupons) if coupons and rnd.random() < 0.3 else None
            result = coupon.evaluate(subtotal) if coupon else {"valid": False, "discount": 0}
            discount = result["discount"] if result["valid"] else 0
            shipping = 0 if subtotal >= 999 else 79
            method = rnd.choice(["razorpay", "razorpay", "razorpay", "cod"])
            age = timedelta(days=rnd.triangular(0, days, 0), hours=rnd.randint(0, 23))
            status = rnd.choices(["delivered", "shipped", "processing", "pending", "cancelled"], [50, 15, 20, 5, 6])[0]
            if age < timedelta(days=2) and status == "delivered":
                status = "processing"
            paid = "paid" if method == "razorpay" and status != "pending" else ("paid" if status == "delivered" else "pending")
            if status == "cancelled" and method == "razorpay":
                paid = rnd.choice(["failed", "refunded"])
            order = Order.objects.create(
                user=user, email=user.email if user else name.lower().replace(" ", ".") + "@guest.example.com",
                subtotal=subtotal, discount=discount, coupon=coupon if result["valid"] else None,
                coupon_code=coupon.code if result["valid"] else None, shipping=shipping, total=subtotal - discount + shipping,
                shipping_address={"name": name, "phone": f"98{rnd.randint(10000000, 99999999)}", "line1": f"{rnd.randint(1, 250)}, Sunrise Residency",
                                  "line2": "", "city": city, "state": state, "pincode": pin},
                payment_method=method, payment_status=paid, status=status, stock_released=status == "cancelled",
                courier="Delhivery" if status in ("shipped", "delivered") else "",
                tracking_url=f"https://www.delhivery.com/track/package/{rnd.randint(10**9, 10**10)}" if status in ("shipped", "delivered") else None,
                gift_note=rnd.choice(["", "", "", "Happy Diwali! Love, Didi"]),
            )
            if result["valid"] and status != "cancelled":
                Coupon.objects.filter(pk=coupon.pk).update(times_used=F("times_used") + 1)
            OrderItem.objects.bulk_create([OrderItem(order=order, product=p, slug=p.slug, name=p.name, color=p.color, size=p.size,
                                                     price=p.price, quantity=q) for p, q in lines])
            created = now - age
            Order.objects.filter(pk=order.pk).update(created_at=created)
            ev = OrderEvent.objects.create(order=order, message="Order placed", actor="Customer")
            OrderEvent.objects.filter(pk=ev.pk).update(created_at=created)
            if status != "cancelled":
                for p, q in lines:
                    Product.objects.filter(pk=p.pk, stock__gte=q).update(stock=F("stock") - q)

        samples = [("Bulk order for Diwali", "bulk", "Hi, we need 120 candles for our office Diwali hampers. Can you do custom labels with our logo?"),
                   ("Where is my order?", "order", "My order was supposed to arrive yesterday. Could you share the tracking link?"),
                   ("Wedding favours", "custom", "Do you make small 50g candles for wedding favours? We need around 200.")]
        for i, (subject, topic, text) in enumerate(samples):
            ContactMessage.objects.get_or_create(email=f"{NAMES[i].split()[0].lower()}@example.com", topic=topic,
                                                 defaults={"name": NAMES[i], "message": text})
        for n in NAMES[:10]:
            NewsletterSubscriber.objects.get_or_create(email=n.split()[0].lower() + ".news@example.com")
        self.stdout.write(self.style.SUCCESS(f"Created {count} demo orders across {len(customers)} customers."))
