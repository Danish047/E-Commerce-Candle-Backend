"""Cancel online orders that were never paid and put their stock back.
Run every 15 minutes with cron / a scheduler:

    */15 * * * *  cd /app && python manage.py release_unpaid_orders
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import StoreSettings
from orders import services
from orders.models import Order


class Command(BaseCommand):
    help = "Cancel unpaid Razorpay orders older than the timeout in store settings"

    def handle(self, *args, **opts):
        minutes = StoreSettings.load().unpaid_order_timeout_minutes
        cutoff = timezone.now() - timedelta(minutes=minutes)
        stale = Order.objects.filter(payment_method="razorpay", payment_status__in=["pending", "failed"],
                                     status="pending", created_at__lt=cutoff)
        n = 0
        for order in stale:
            services.change_status(order, "cancelled", "System (payment not completed)")
            n += 1
        self.stdout.write(self.style.SUCCESS(f"Released {n} unpaid order(s)."))
