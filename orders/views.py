import json
import logging

from django.conf import settings
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiTypes, extend_schema

from . import services
from .models import Order, OrderItem, check_coupon
from .serializers import OrderSerializer

log = logging.getLogger(__name__)


def orders_qs():
    return Order.objects.prefetch_related(Prefetch("items", queryset=OrderItem.objects.order_by("id")))


class CouponValidateView(APIView):
    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        try:
            subtotal = int(request.data.get("subtotal") or 0)
        except (TypeError, ValueError):
            subtotal = 0
        _, result = check_coupon(request.data.get("code"), subtotal)
        return Response(result)


class OrderListCreateView(APIView):
    def get_permissions(self):
        return [IsAuthenticated()] if self.request.method == "GET" else []

    @extend_schema(responses=OrderSerializer(many=True))
    def get(self, request):
        return Response(OrderSerializer(orders_qs().filter(user=request.user), many=True).data)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        user = request.user if request.user.is_authenticated else None
        order, razorpay = services.place_order(user=user, data=request.data)
        order = orders_qs().get(pk=order.pk)
        return Response({"order": OrderSerializer(order).data, "razorpay": razorpay}, status=201)


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OrderSerializer)
    def get(self, request, order_number):
        order = get_object_or_404(orders_qs(), order_number=order_number, user=request.user)
        return Response(OrderSerializer(order).data)


class PaymentVerifyView(APIView):
    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        d = request.data
        order = get_object_or_404(Order, order_number=d.get("order_number"))
        if d.get("razorpay_order_id") != order.razorpay_order_id:
            raise ValidationError({"detail": "Payment does not match this order."})
        if not services.verify_signature(order.razorpay_order_id, d.get("razorpay_payment_id"), d.get("razorpay_signature")):
            order.payment_status = "failed"
            order.save(update_fields=["payment_status"])
            services.log_event(order, "Payment signature check failed")
            raise ValidationError({"detail": "Payment could not be verified. If money was deducted, it will be refunded automatically."})
        order = services.mark_paid(order, d.get("razorpay_payment_id"))
        return Response({"order": OrderSerializer(orders_qs().get(pk=order.pk)).data})


@method_decorator(csrf_exempt, name="dispatch")
class RazorpayWebhookView(APIView):
    """Backup for when the shopper closes the tab before /payments/verify/ runs.
    Point Razorpay → Webhooks at /api/payments/webhook/ with events payment.captured and payment.failed."""

    authentication_classes = []

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: None, 400: None, 503: None})
    def post(self, request):
        import hashlib
        import hmac

        secret = settings.RAZORPAY_WEBHOOK_SECRET
        signature = request.headers.get("X-Razorpay-Signature", "")
        if not secret:
            return HttpResponse(status=503)
        expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return HttpResponse(status=400)

        payload = json.loads(request.body or b"{}")
        payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
        order = Order.objects.filter(razorpay_order_id=payment.get("order_id")).first()
        if order:
            if payload.get("event") == "payment.captured":
                services.mark_paid(order, payment.get("id"), actor="Razorpay webhook")
            elif payload.get("event") == "payment.failed" and order.payment_status == "pending":
                services.log_event(order, "Payment attempt failed", "Razorpay webhook")
        return HttpResponse(status=200)
