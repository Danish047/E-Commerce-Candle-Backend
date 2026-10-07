from rest_framework import serializers

from .models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(read_only=True)
    line_total = serializers.IntegerField(read_only=True)

    class Meta:
        model = OrderItem
        fields = ["product_id", "slug", "name", "color", "size", "price", "quantity", "line_total"]


class OrderSerializer(serializers.ModelSerializer):
    """Exact shape from API_CONTRACT.md."""

    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "order_number", "email", "items", "subtotal", "discount", "coupon_code", "shipping", "total",
            "shipping_address", "gift_note", "payment_method", "payment_status", "status", "tracking_url", "created_at",
        ]
