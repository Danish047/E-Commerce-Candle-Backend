"""Order rules live here so the storefront API, admin panel and webhooks share them."""
import hashlib
import hmac
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import F
from rest_framework.exceptions import APIException, ValidationError

from catalog.models import Product
from core import emails
from core.models import StoreSettings

from .models import Coupon, Order, OrderEvent, OrderItem, check_coupon

log = logging.getLogger(__name__)
REQUIRED_ADDRESS = ["name", "phone", "line1", "city", "state", "pincode"]


class PaymentsNotConfigured(APIException):
    status_code = 503
    default_detail = "Online payments are not set up yet. Please choose cash on delivery."


def razorpay_client():
    if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
        raise PaymentsNotConfigured()
    import razorpay

    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def log_event(order, message, actor="System"):
    OrderEvent.objects.create(order=order, message=message, actor=actor)


@transaction.atomic
def place_order(*, user, data):
    items = data.get("items") or []
    addr = data.get("shipping_address") or {}
    method = data.get("payment_method")
    email = (user.email if user else str(data.get("email") or "").strip().lower())
    store = StoreSettings.load()

    if not items:
        raise ValidationError({"detail": "Your cart is empty."})
    if any(not str(addr.get(k, "")).strip() for k in REQUIRED_ADDRESS):
        raise ValidationError({"detail": "Please fill in the full shipping address."})
    if not email:
        raise ValidationError({"detail": "Email is required."})
    if method not in ("razorpay", "cod"):
        raise ValidationError({"detail": "Choose a payment method."})
    pin = store.pincode_info(str(addr["pincode"]))
    if not pin["serviceable"]:
        raise ValidationError({"detail": f"Sorry, we don't deliver to {addr['pincode']} yet."})

    # Lock the product rows so two shoppers can't buy the last candle twice
    wanted = {}
    for line in items:
        pid, qty = int(line.get("product_id", 0)), int(line.get("quantity", 0))
        if qty > 0:
            wanted[pid] = wanted.get(pid, 0) + qty
    products = {p.id: p for p in Product.objects.select_for_update().filter(id__in=wanted, is_active=True)}

    lines, subtotal = [], 0
    for pid, qty in wanted.items():
        p = products.get(pid)
        if not p:
            raise ValidationError({"detail": "A product in your cart is no longer available."})
        if qty > p.stock:
            raise ValidationError({"detail": f"Only {p.stock} left of {p.name}." if p.stock else f"{p.name} is sold out."})
        lines.append((p, qty))
        subtotal += p.price * qty

    coupon, result = (None, {"valid": False, "discount": 0})
    if data.get("coupon_code"):
        coupon, result = check_coupon(data["coupon_code"], subtotal)
    discount = result["discount"] if result["valid"] else 0
    shipping = store.shipping_for(subtotal)
    total = subtotal - discount + shipping

    if method == "cod" and (not pin["cod_available"] or total > store.cod_max_order):
        raise ValidationError({"detail": "Cash on delivery isn't available for this order. Please pay online."})

    order = Order.objects.create(
        user=user, email=email, subtotal=subtotal, discount=discount,
        coupon=coupon if result["valid"] else None, coupon_code=result.get("code") if result["valid"] else None,
        shipping=shipping, total=total,
        shipping_address={k: str(addr.get(k, "")).strip() for k in REQUIRED_ADDRESS + ["line2"]},
        gift_note=str(data.get("gift_note") or "")[:500], payment_method=method,
        status="processing" if method == "cod" else "pending",
    )
    OrderItem.objects.bulk_create([
        OrderItem(order=order, product=p, slug=p.slug, name=p.name, color=p.color, size=p.size, price=p.price, quantity=q)
        for p, q in lines
    ])
    for p, q in lines:
        Product.objects.filter(pk=p.pk).update(stock=F("stock") - q)

    log_event(order, f"Order placed ({order.get_payment_method_display()})", "Customer")

    razorpay = None
    if method == "razorpay":
        rz = razorpay_client().order.create({
            "amount": total * 100, "currency": "INR", "receipt": order.order_number,
            "notes": {"order_number": order.order_number},
        })
        order.razorpay_order_id = rz["id"]
        order.save(update_fields=["razorpay_order_id"])
        razorpay = {"order_id": rz["id"], "amount": total * 100, "currency": "INR", "key": settings.RAZORPAY_KEY_ID}
    else:
        _use_coupon(order)
        transaction.on_commit(lambda: emails.order_placed(order))

    return order, razorpay


def _use_coupon(order):
    if order.coupon_id:
        Coupon.objects.filter(pk=order.coupon_id).update(times_used=F("times_used") + 1)


def verify_signature(razorpay_order_id, payment_id, signature):
    if not settings.RAZORPAY_KEY_SECRET:
        raise PaymentsNotConfigured()
    msg = f"{razorpay_order_id}|{payment_id}".encode()
    expected = hmac.new(settings.RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@transaction.atomic
def mark_paid(order, payment_id, actor="Customer"):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_status == "paid":
        return order
    order.payment_status = "paid"
    order.razorpay_payment_id = payment_id or order.razorpay_payment_id
    if order.status == "pending":
        order.status = "processing"
    order.save(update_fields=["payment_status", "razorpay_payment_id", "status", "updated_at"])
    _use_coupon(order)
    log_event(order, f"Payment received ({payment_id})", actor)
    transaction.on_commit(lambda: emails.order_placed(order))
    return order


@transaction.atomic
def release_stock(order):
    """Put stock back when an order is cancelled. Safe to call twice."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.stock_released:
        return order
    for item in order.items.exclude(product=None):
        Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)
    order.stock_released = True
    order.save(update_fields=["stock_released"])
    return order


def change_status(order, new_status, actor):
    old = order.status
    if new_status == old:
        return order
    if old == "cancelled":
        raise ValidationError({"detail": "A cancelled order can't be reopened. Ask the customer to order again."})
    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    if new_status == "cancelled":
        release_stock(order)
        if order.payment_status == "pending":
            Order.objects.filter(pk=order.pk).update(payment_status="failed")
            order.payment_status = "failed"
    log_event(order, f"Status changed from {old} to {new_status}", actor)
    transaction.on_commit(lambda: emails.order_status_changed(order))
    return order
