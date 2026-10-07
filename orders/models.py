from django.conf import settings
from django.db import models
from django.utils import timezone


class Coupon(models.Model):
    PERCENT, FLAT = "percent", "flat"

    code = models.CharField(max_length=30, unique=True)
    type = models.CharField(max_length=10, choices=[(PERCENT, "Percent off"), (FLAT, "Flat ₹ off")], default=PERCENT)
    value = models.PositiveIntegerField(help_text="Percent (e.g. 10) or rupees (e.g. 150)")
    max_discount = models.PositiveIntegerField(null=True, blank=True, help_text="Cap for percent coupons")
    min_order = models.PositiveIntegerField(default=0)
    description = models.CharField(max_length=160, blank=True)
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Total uses allowed; blank = unlimited")
    times_used = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_active", "code"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def evaluate(self, subtotal):
        """Returns the contract response for /coupons/validate/."""
        now = timezone.now()
        invalid = {"valid": False, "discount": 0}
        if not self.is_active or (self.starts_at and now < self.starts_at):
            return {**invalid, "message": "Invalid coupon code"}
        if self.expires_at and now > self.expires_at:
            return {**invalid, "message": f"{self.code} has expired"}
        if self.usage_limit is not None and self.times_used >= self.usage_limit:
            return {**invalid, "message": f"{self.code} has been fully redeemed"}
        if subtotal < self.min_order:
            return {**invalid, "message": f"Add ₹{self.min_order - subtotal:,} more to use {self.code}"}
        if self.type == self.PERCENT:
            discount = round(subtotal * self.value / 100)
            if self.max_discount:
                discount = min(discount, self.max_discount)
        else:
            discount = self.value
        discount = min(discount, subtotal)
        return {"valid": True, "code": self.code, "discount": discount, "message": self.description or f"{self.code} applied"}


def check_coupon(code, subtotal):
    code = str(code or "").strip().upper()
    coupon = Coupon.objects.filter(code=code).first() if code else None
    if not coupon:
        return None, {"valid": False, "discount": 0, "message": "Invalid coupon code"}
    return coupon, coupon.evaluate(subtotal)


class Order(models.Model):
    STATUS = [
        ("pending", "Pending payment"),
        ("processing", "Processing"),
        ("shipped", "Shipped"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    ]
    PAYMENT_STATUS = [("pending", "Pending"), ("paid", "Paid"), ("failed", "Failed"), ("refunded", "Refunded")]
    PAYMENT_METHODS = [("razorpay", "Online (Razorpay)"), ("cod", "Cash on delivery")]

    order_number = models.CharField(max_length=20, unique=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    email = models.EmailField()

    subtotal = models.PositiveIntegerField()
    discount = models.PositiveIntegerField(default=0)
    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    coupon_code = models.CharField(max_length=30, blank=True, null=True)
    shipping = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField()

    shipping_address = models.JSONField()
    gift_note = models.TextField(blank=True)

    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS)
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS, default="pending")
    razorpay_order_id = models.CharField(max_length=60, blank=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=60, blank=True)

    status = models.CharField(max_length=12, choices=STATUS, default="pending")
    tracking_url = models.URLField(blank=True, null=True, max_length=500)
    courier = models.CharField(max_length=60, blank=True)
    admin_note = models.TextField(blank=True, help_text="Only visible to staff")
    stock_released = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.order_number:
            self.order_number = f"{settings.ORDER_PREFIX}{10240 + self.pk}"
            Order.objects.filter(pk=self.pk).update(order_number=self.order_number)

    @property
    def customer_name(self):
        return (self.shipping_address or {}).get("name") or (self.user.name if self.user else "")


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.SET_NULL, null=True, related_name="order_items")
    # Snapshot, so edits to the product never change past orders
    slug = models.CharField(max_length=120)
    name = models.CharField(max_length=120)
    color = models.CharField(max_length=9, blank=True)
    size = models.CharField(max_length=40, blank=True)
    price = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField()

    @property
    def line_total(self):
        return self.price * self.quantity


class OrderEvent(models.Model):
    """Timeline shown on the admin order page."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    message = models.CharField(max_length=255)
    actor = models.CharField(max_length=120, blank=True, help_text="Staff name, 'Customer' or 'System'")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
