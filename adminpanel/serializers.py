from django.db import transaction
from rest_framework import serializers
from drf_spectacular.utils import OpenApiTypes, extend_schema_field

from accounts.models import User
from catalog.models import Category, Mood, Occasion, Product, ProductImage, Review
from core.models import ContactMessage, NewsletterSubscriber, QuizQuestion, StoreSettings
from orders.models import Coupon, Order, OrderEvent, OrderItem


# ── Catalog ────────────────────────────────────────────
class CategoryAdminSerializer(serializers.ModelSerializer):
    product_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = ["id", "slug", "name", "description", "sort_order", "product_count"]
        extra_kwargs = {"slug": {"required": False}}


class MoodAdminSerializer(serializers.ModelSerializer):
    product_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Mood
        fields = ["id", "slug", "name", "sort_order", "product_count"]
        extra_kwargs = {"slug": {"required": False}}


class OccasionAdminSerializer(MoodAdminSerializer):
    class Meta(MoodAdminSerializer.Meta):
        model = Occasion


class ProductImageSerializer(serializers.ModelSerializer):
    src = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ["id", "src", "sort_order"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_src(self, obj):
        return obj.src(self.context.get("request"))


class NotesField(serializers.JSONField):
    def to_internal_value(self, data):
        data = super().to_internal_value(data) or {}
        clean = {}
        for layer in ("top", "middle", "base"):
            vals = data.get(layer) or []
            if isinstance(vals, str):
                vals = vals.split(",")
            clean[layer] = [str(v).strip() for v in vals if str(v).strip()][:8]
        return clean


class ProductAdminSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    moods = serializers.PrimaryKeyRelatedField(queryset=Mood.objects.all(), many=True, required=False)
    occasions = serializers.PrimaryKeyRelatedField(queryset=Occasion.objects.all(), many=True, required=False)
    notes = NotesField(required=False)
    category_name = serializers.CharField(source="category.name", read_only=True)
    images = ProductImageSerializer(source="photos", many=True, read_only=True)
    rating = serializers.FloatField(read_only=True)
    units_sold = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Product
        fields = [
            "id", "slug", "name", "tagline", "description", "price", "compare_price", "size", "sku",
            "category", "category_name", "moods", "occasions", "notes",
            "burn_time_hours", "wax_type", "wick_type", "fragrance_load",
            "stock", "color", "is_active", "is_bestseller", "is_new",
            "rating", "reviews_count", "images", "units_sold", "created_at", "updated_at",
        ]
        read_only_fields = ["reviews_count", "created_at", "updated_at"]
        extra_kwargs = {"slug": {"required": False}}

    def validate_slug(self, v):
        qs = Product.objects.filter(slug=v)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if v and qs.exists():
            raise serializers.ValidationError("Another product already uses this web address.")
        return v

    def validate_color(self, v):
        import re

        if not re.match(r"^#[0-9A-Fa-f]{6}$", v or ""):
            raise serializers.ValidationError("Use a hex colour like #C99A6B.")
        return v

    def validate(self, data):
        price = data.get("price", getattr(self.instance, "price", 0))
        compare = data.get("compare_price", getattr(self.instance, "compare_price", None))
        if compare and compare <= price:
            raise serializers.ValidationError({"compare_price": "MRP must be higher than the selling price, or leave it empty."})
        return data


# ── Orders ─────────────────────────────────────────────
class OrderItemAdminSerializer(serializers.ModelSerializer):
    line_total = serializers.IntegerField(read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "product_id", "slug", "name", "color", "size", "price", "quantity", "line_total"]


class OrderEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderEvent
        fields = ["id", "message", "actor", "created_at"]


class OrderListAdminSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(read_only=True)
    items_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Order
        fields = ["id", "order_number", "customer_name", "email", "items_count", "total",
                  "payment_method", "payment_status", "status", "created_at"]


class OrderDetailAdminSerializer(serializers.ModelSerializer):
    items = OrderItemAdminSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(read_only=True)
    customer = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "order_number", "customer_name", "customer", "email", "items", "subtotal", "discount", "coupon_code",
            "shipping", "total", "shipping_address", "gift_note", "payment_method", "payment_status",
            "razorpay_order_id", "razorpay_payment_id", "status", "tracking_url", "courier", "admin_note",
            "events", "created_at", "updated_at",
        ]
        read_only_fields = [f for f in fields if f not in ("status", "payment_status", "tracking_url", "courier", "admin_note")]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_customer(self, obj):
        if not obj.user:
            return None
        return {"id": obj.user.id, "name": obj.user.name, "orders_count": obj.user.orders.count()}


class CouponAdminSerializer(serializers.ModelSerializer):
    revenue = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Coupon
        fields = ["id", "code", "type", "value", "max_discount", "min_order", "description", "is_active",
                  "starts_at", "expires_at", "usage_limit", "times_used", "revenue", "created_at"]
        read_only_fields = ["times_used", "created_at"]

    def validate(self, data):
        t = data.get("type", getattr(self.instance, "type", "percent"))
        v = data.get("value", getattr(self.instance, "value", 0))
        if t == "percent" and not 1 <= v <= 90:
            raise serializers.ValidationError({"value": "Percent must be between 1 and 90."})
        s, e = data.get("starts_at"), data.get("expires_at")
        if s and e and e <= s:
            raise serializers.ValidationError({"expires_at": "End date must be after the start date."})
        return data


# ── People ─────────────────────────────────────────────
class CustomerAdminSerializer(serializers.ModelSerializer):
    orders_count = serializers.IntegerField(read_only=True, default=0)
    total_spent = serializers.IntegerField(read_only=True, default=0)
    last_order_at = serializers.DateTimeField(read_only=True, default=None)

    class Meta:
        model = User
        fields = ["id", "name", "email", "phone", "is_active", "date_joined", "last_login",
                  "orders_count", "total_spent", "last_order_at"]
        read_only_fields = ["name", "email", "phone", "date_joined", "last_login"]


class StaffAdminSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    role = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "name", "email", "phone", "is_superuser", "is_active", "role", "last_login", "date_joined", "password"]
        read_only_fields = ["last_login", "date_joined"]

    def validate_email(self, v):
        v = v.lower().strip()
        qs = User.objects.filter(email=v)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Someone already uses this email.")
        return v

    @transaction.atomic
    def create(self, data):
        password = data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "Set a password of at least 8 characters."})
        existing = User.objects.filter(email=data["email"]).first()
        user = existing or User(**data)
        for k, v in data.items():
            setattr(user, k, v)
        user.is_staff = True
        user.set_password(password)
        user.save()
        return user

    def update(self, user, data):
        password = data.pop("password", None)
        for k, v in data.items():
            setattr(user, k, v)
        if password:
            user.set_password(password)
        user.save()
        return user


class ReviewAdminSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_slug = serializers.CharField(source="product.slug", read_only=True)
    product_color = serializers.CharField(source="product.color", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "product_id", "product_name", "product_slug", "product_color", "user_name", "rating",
                  "title", "comment", "verified", "is_approved", "created_at"]
        read_only_fields = [f for f in fields if f != "is_approved"]


class MessageAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["id", "name", "email", "phone", "topic", "message", "is_resolved", "admin_note", "created_at"]
        read_only_fields = ["name", "email", "phone", "topic", "message", "created_at"]


class SubscriberAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsletterSubscriber
        fields = ["id", "email", "is_active", "created_at"]
        read_only_fields = ["email", "created_at"]


class QuizQuestionAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizQuestion
        fields = ["id", "key", "question", "options", "sort_order"]

    def validate_options(self, v):
        if not isinstance(v, list) or len(v) < 2:
            raise serializers.ValidationError("Add at least two answers.")
        for o in v:
            if not isinstance(o, dict) or not o.get("value") or not o.get("label"):
                raise serializers.ValidationError("Each answer needs a label and a matching value.")
        return v


class StoreSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreSettings
        exclude = ["id"]
        read_only_fields = ["updated_at"]
