"""Transactional emails. Failures are logged and never break a request."""
import logging

from django.conf import settings
from django.core.mail import send_mail

log = logging.getLogger(__name__)


def _send(subject, body, to):
    to = [x for x in to if x]
    if not to:
        return
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, to, fail_silently=False)
    except Exception:  # noqa: BLE001
        log.exception("Email failed: %s", subject)


def _lines(order):
    return "\n".join(f"  {i.quantity} × {i.name} ({i.size}) — ₹{i.line_total:,}" for i in order.items.all())


def order_placed(order):
    from .models import StoreSettings

    store = StoreSettings.load()
    pay = "Cash on delivery" if order.payment_method == "cod" else "Paid online"
    body = (
        f"Hi {order.shipping_address.get('name', '')},\n\n"
        f"Thank you for your order {order.order_number}. We're hand-pouring it now.\n\n"
        f"{_lines(order)}\n\nTotal: ₹{order.total:,} ({pay})\n\n"
        f"We'll email you again when it ships.\n\n— {store.store_name}"
    )
    _send(f"Order {order.order_number} confirmed", body, [order.email])
    _send(f"New order {order.order_number} · ₹{order.total:,}", f"{_lines(order)}\n\nCustomer: {order.email}",
          [settings.STORE_ALERT_EMAIL])


def order_status_changed(order):
    from .models import StoreSettings

    store = StoreSettings.load()
    messages = {
        "shipped": "is on its way" + (f". Track it here: {order.tracking_url}" if order.tracking_url else ""),
        "delivered": "has been delivered. We hope it makes your home smell lovely",
        "cancelled": "has been cancelled. If you paid online, the refund will reach you in 5–7 working days",
    }
    if order.status not in messages:
        return
    body = f"Hi,\n\nYour order {order.order_number} {messages[order.status]}.\n\n— {store.store_name}"
    _send(f"Order {order.order_number}: {order.get_status_display()}", body, [order.email])


def contact_received(msg):
    _send(f"New message: {msg.topic or 'Contact form'} from {msg.name}",
          f"{msg.message}\n\nReply to: {msg.email} {msg.phone}", [settings.STORE_ALERT_EMAIL])
