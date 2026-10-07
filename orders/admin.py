from django.contrib import admin

from .models import Coupon, Order, OrderEvent, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["product", "name", "size", "price", "quantity"]
    exclude = ["slug", "color"]


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ["message", "actor", "created_at"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["order_number", "email", "total", "payment_method", "payment_status", "status", "created_at"]
    list_filter = ["status", "payment_status", "payment_method"]
    search_fields = ["order_number", "email", "razorpay_payment_id"]
    readonly_fields = ["order_number", "subtotal", "discount", "shipping", "total", "razorpay_order_id", "razorpay_payment_id"]
    inlines = [OrderItemInline, OrderEventInline]


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ["code", "type", "value", "min_order", "is_active", "times_used", "usage_limit", "expires_at"]
    list_editable = ["is_active"]
