from django.db import models


class StoreSettings(models.Model):
    """Single row of store-wide rules the owner edits in the admin panel."""

    store_name = models.CharField(max_length=80, default="Lumière & Co.")
    support_email = models.EmailField(default="hello@lumiere.co.in")
    support_phone = models.CharField(max_length=20, blank=True)

    free_shipping_above = models.PositiveIntegerField(default=999)
    shipping_fee = models.PositiveIntegerField(default=79)

    cod_enabled = models.BooleanField(default=True)
    cod_max_order = models.PositiveIntegerField(default=5000, help_text="COD hidden above this order total")
    blocked_pincodes = models.TextField(blank=True, help_text="Pincodes or 3-digit prefixes you can't ship to, comma separated")
    metro_prefixes = models.CharField(max_length=200, default="11,40,56,60,70,50,45", help_text="2-digit pincode prefixes with faster delivery")
    metro_days = models.CharField(max_length=10, default="2-3")
    standard_days = models.CharField(max_length=10, default="4-6")

    low_stock_threshold = models.PositiveIntegerField(default=10)
    unpaid_order_timeout_minutes = models.PositiveIntegerField(default=60, help_text="Unpaid online orders are cancelled and stock released after this")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "store settings"

    def __str__(self):
        return "Store settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def _csv(self, value):
        return [x.strip() for x in value.split(",") if x.strip()]

    def pincode_info(self, pincode):
        blocked = any(pincode.startswith(b) for b in self._csv(self.blocked_pincodes))
        metro = pincode[:2] in self._csv(self.metro_prefixes)
        return {
            "pincode": pincode,
            "serviceable": not blocked,
            "cod_available": (not blocked) and self.cod_enabled,
            "estimated_days": self.metro_days if metro else self.standard_days,
        }

    def shipping_for(self, subtotal):
        return 0 if subtotal >= self.free_shipping_above else self.shipping_fee


class ContactMessage(models.Model):
    TOPICS = [("order", "Order"), ("bulk", "Bulk / corporate"), ("custom", "Custom candles"), ("other", "Other")]

    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    topic = models.CharField(max_length=60, blank=True)
    message = models.TextField()
    is_resolved = models.BooleanField(default=False)
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_resolved", "-created_at"]

    def __str__(self):
        return f"{self.name}: {self.topic}"


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.email


class QuizQuestion(models.Model):
    """Question ids the store uses: mood, category, occasion.
    options: [{"value": "calm", "label": "Calm & relaxed"}]"""

    key = models.SlugField(unique=True, help_text="mood, category or occasion")
    question = models.CharField(max_length=200)
    options = models.JSONField(default=list)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.question
