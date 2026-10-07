import csv
from datetime import date, datetime, time, timedelta

from django.contrib.auth import authenticate
from django.db.models import Count, Max, Q, Sum, Value
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Coalesce, TruncDate
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from accounts.models import User
from accounts.serializers import StaffUserSerializer, tokens_for
from catalog.models import Category, Mood, Occasion, Product, ProductImage, Review
from catalog.views import StorePagination
from core.models import ContactMessage, NewsletterSubscriber, QuizQuestion, StoreSettings
from orders import services
from orders.models import Coupon, Order

from . import serializers as s
from .permissions import IsOwner, IsStaff, StaffReadOwnerWrite

# Revenue counts paid online orders and COD orders that weren't cancelled
COUNTED = Q(payment_status="paid") | Q(payment_method="cod", payment_status__in=["pending", "paid"])
COUNTED &= ~Q(status="cancelled")


SPENT = (Q(orders__payment_status="paid") | Q(orders__payment_method="cod")) & ~Q(orders__status="cancelled")


class AdminPagination(StorePagination):
    page_size = 20
    max_page_size = 200


def csv_response(filename, header, rows):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("\ufeff")  # Excel-friendly UTF-8
    w = csv.writer(resp)
    w.writerow(header)
    w.writerows(rows)
    return resp


def actor(request):
    return request.user.name or request.user.email


class StaffViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStaff]
    pagination_class = AdminPagination


# ── Auth ───────────────────────────────────────────────
class AdminLoginView(APIView):
    throttle_scope = "admin_login"
    permission_classes = []

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        email = str(request.data.get("email", "")).lower().strip()
        user = authenticate(request, email=email, password=request.data.get("password", ""))
        if not user:
            raise AuthenticationFailed("That email and password don't match.")
        if not user.is_staff:
            raise PermissionDenied("This account doesn't have admin access.")
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        return Response(tokens_for(user, StaffUserSerializer))


class AdminMeView(APIView):
    permission_classes = [IsStaff]

    @extend_schema(responses=StaffUserSerializer)
    def get(self, request):
        return Response(StaffUserSerializer(request.user).data)

    @extend_schema(request=OpenApiTypes.OBJECT, responses=StaffUserSerializer)
    def patch(self, request):
        user = request.user
        for f in ("name", "phone"):
            if f in request.data:
                setattr(user, f, str(request.data[f]).strip())
        if not user.name:
            raise ValidationError({"name": ["Name can't be empty."]})
        user.save()
        return Response(StaffUserSerializer(user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsStaff]

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        current, new = request.data.get("current_password", ""), request.data.get("new_password", "")
        if not request.user.check_password(current):
            raise ValidationError({"current_password": ["Current password is wrong."]})
        if len(new) < 8:
            raise ValidationError({"new_password": ["Use at least 8 characters."]})
        request.user.set_password(new)
        request.user.save()
        return Response({"detail": "Password updated."})


# ── Dashboard ──────────────────────────────────────────
def _pct(now, before):
    if not before:
        return None
    return round((now - before) * 100 / before, 1)


class DashboardView(APIView):
    permission_classes = [IsStaff]

    @extend_schema(
        parameters=[OpenApiParameter("days", int, OpenApiParameter.QUERY)],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request):
        days = max(1, min(int(request.query_params.get("days", 30) or 30), 365))
        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        start_day = today - timedelta(days=days - 1)
        start = datetime.combine(start_day, time.min, tzinfo=tz)
        prev_start = start - timedelta(days=days)

        cur = Order.objects.filter(created_at__gte=start)
        prev = Order.objects.filter(created_at__gte=prev_start, created_at__lt=start)

        def kpis(qs):
            agg = qs.filter(COUNTED).aggregate(revenue=Coalesce(Sum("total"), 0), orders=Count("id"))
            agg["aov"] = round(agg["revenue"] / agg["orders"]) if agg["orders"] else 0
            return agg

        k, kp = kpis(cur), kpis(prev)
        new_customers = User.objects.filter(is_staff=False, date_joined__gte=start).count()
        prev_customers = User.objects.filter(is_staff=False, date_joined__gte=prev_start, date_joined__lt=start).count()

        daily = {
            row["day"]: row
            for row in cur.filter(COUNTED).annotate(day=TruncDate("created_at", tzinfo=tz))
            .values("day").annotate(revenue=Sum("total"), orders=Count("id"))
        }
        series = []
        for i in range(days):
            d = start_day + timedelta(days=i)
            row = daily.get(d, {})
            series.append({"date": d.isoformat(), "revenue": row.get("revenue", 0), "orders": row.get("orders", 0)})

        top = (
            Product.objects.filter(order_items__order__in=cur.filter(COUNTED))
            .annotate(quantity=Sum("order_items__quantity"))
            .order_by("-quantity")[:5]
        )
        top_products = []
        for p in top:
            revenue = sum(i.price * i.quantity for i in p.order_items.filter(order__in=cur.filter(COUNTED)))
            top_products.append({"id": p.id, "name": p.name, "color": p.color, "quantity": p.quantity, "revenue": revenue})

        settings_ = StoreSettings.load()
        low = Product.objects.filter(is_active=True, stock__lte=settings_.low_stock_threshold).order_by("stock")[:8]

        by_status = dict(cur.values_list("status").annotate(n=Count("id")))
        by_method = dict(cur.filter(COUNTED).values_list("payment_method").annotate(n=Sum("total")))

        recent = Order.objects.annotate(items_count=Count("items")).order_by("-created_at")[:6]

        return Response({
            "days": days,
            "kpis": {
                "revenue": k["revenue"], "revenue_change": _pct(k["revenue"], kp["revenue"]),
                "orders": k["orders"], "orders_change": _pct(k["orders"], kp["orders"]),
                "aov": k["aov"], "aov_change": _pct(k["aov"], kp["aov"]),
                "customers": new_customers, "customers_change": _pct(new_customers, prev_customers),
            },
            "series": series,
            "status_breakdown": [{"status": key, "count": by_status.get(key, 0)} for key, _ in Order.STATUS],
            "payment_split": [{"method": m, "revenue": by_method.get(m, 0)} for m in ("razorpay", "cod")],
            "top_products": top_products,
            "low_stock": [{"id": p.id, "name": p.name, "stock": p.stock, "color": p.color} for p in low],
            "low_stock_threshold": settings_.low_stock_threshold,
            "attention": {
                "to_ship": Order.objects.filter(status="processing").count(),
                "awaiting_payment": Order.objects.filter(status="pending").count(),
                "open_messages": ContactMessage.objects.filter(is_resolved=False).count(),
                "out_of_stock": Product.objects.filter(is_active=True, stock=0).count(),
            },
            "recent_orders": s.OrderListAdminSerializer(recent, many=True).data,
        })


class SearchView(APIView):
    """Top-bar quick search across orders, products and customers."""

    permission_classes = [IsStaff]

    @extend_schema(
        parameters=[OpenApiParameter("q", str, OpenApiParameter.QUERY)],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if len(q) < 2:
            return Response({"orders": [], "products": [], "customers": []})
        orders = Order.objects.filter(
            Q(order_number__icontains=q) | Q(email__icontains=q) | Q(shipping_address__name__icontains=q)
        )[:5]
        products = Product.objects.filter(Q(name__icontains=q) | Q(sku__icontains=q))[:5]
        customers = User.objects.filter(is_staff=False).filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))[:5]
        return Response({
            "orders": [{"order_number": o.order_number, "customer_name": o.customer_name, "total": o.total, "status": o.status} for o in orders],
            "products": [{"id": p.id, "name": p.name, "color": p.color, "stock": p.stock} for p in products],
            "customers": [{"id": c.id, "name": c.name, "email": c.email} for c in customers],
        })


# ── Catalog ────────────────────────────────────────────
class ProductViewSet(StaffViewSet):
    serializer_class = s.ProductAdminSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        p = self.request.query_params
        qs = (
            Product.objects.select_related("category").prefetch_related("moods", "occasions", "photos")
            .annotate(units_sold=Coalesce(Sum("order_items__quantity", filter=~Q(order_items__order__status="cancelled")), 0))
        )
        if p.get("search"):
            q = p["search"]
            qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(tagline__icontains=q))
        if p.get("category"):
            qs = qs.filter(category_id=p["category"])
        if p.get("status") == "active":
            qs = qs.filter(is_active=True)
        elif p.get("status") == "hidden":
            qs = qs.filter(is_active=False)
        threshold = StoreSettings.load().low_stock_threshold
        if p.get("stock") == "low":
            qs = qs.filter(stock__gt=0, stock__lte=threshold)
        elif p.get("stock") == "out":
            qs = qs.filter(stock=0)
        ordering = p.get("ordering")
        allowed = {"name", "-name", "price", "-price", "stock", "-stock", "-units_sold", "-rating", "-created_at"}
        return qs.order_by(ordering if ordering in allowed else "-created_at", "id")

    def destroy(self, request, *args, **kwargs):
        product = self.get_object()
        if product.order_items.exists():
            product.is_active = False
            product.save(update_fields=["is_active"])
            return Response({"detail": f"{product.name} has past orders, so it was hidden from the store instead of deleted."}, status=200)
        product.delete()
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        src = self.get_object()
        moods, occasions = list(src.moods.all()), list(src.occasions.all())
        src.pk, src.id, src.slug = None, None, ""
        src.name = f"{src.name} (copy)"
        src.is_active, src.stock, src.rating, src.reviews_count = False, 0, 0, 0
        src.save()
        src.moods.set(moods)
        src.occasions.set(occasions)
        return Response(self.get_serializer(self.get_queryset().get(pk=src.pk)).data, status=201)

    @action(detail=True, methods=["post"], url_path="images")
    def add_image(self, request, pk=None):
        product = self.get_object()
        file, url = request.FILES.get("image"), str(request.data.get("url", "")).strip()
        if not file and not url:
            raise ValidationError({"detail": "Choose a photo or paste an image link."})
        if file and file.size > 5 * 1024 * 1024:
            raise ValidationError({"detail": "Photos must be under 5 MB."})
        order = product.photos.count()
        img = ProductImage(product=product, sort_order=order, url=url if not file else "")
        if file:
            img.image = file
        img.full_clean(exclude=["product"])
        img.save()
        return Response(s.ProductImageSerializer(product.photos.all(), many=True, context={"request": request}).data, status=201)

    @action(detail=True, methods=["delete"], url_path=r"images/(?P<image_id>\d+)")
    def remove_image(self, request, pk=None, image_id=None):
        product = self.get_object()
        img = get_object_or_404(ProductImage, pk=image_id, product=product)
        if img.image:
            img.image.delete(save=False)
        img.delete()
        return Response(s.ProductImageSerializer(product.photos.all(), many=True, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="images/reorder")
    def reorder_images(self, request, pk=None):
        product = self.get_object()
        for i, image_id in enumerate(request.data.get("ids", [])):
            product.photos.filter(pk=image_id).update(sort_order=i)
        return Response(s.ProductImageSerializer(product.photos.all(), many=True, context={"request": request}).data)

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk(self, request):
        ids, op = request.data.get("ids", []), request.data.get("action")
        qs = Product.objects.filter(pk__in=ids)
        if op == "show":
            n = qs.update(is_active=True)
        elif op == "hide":
            n = qs.update(is_active=False)
        elif op == "restock":
            n = qs.update(stock=int(request.data.get("stock", 25)))
        else:
            raise ValidationError({"detail": "Unknown action."})
        return Response({"updated": n})


class TaxonomyViewSet(StaffViewSet):
    pagination_class = None
    model = None

    def get_queryset(self):
        return self.model.objects.annotate(product_count=Count("products", distinct=True)).order_by("sort_order", "id")

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        try:
            obj.delete()
        except ProtectedError:
            raise ValidationError({"detail": f"Move the products in {obj.name} to another category first."})
        return Response(status=204)


class CategoryViewSet(TaxonomyViewSet):
    model, serializer_class = Category, s.CategoryAdminSerializer


class MoodViewSet(TaxonomyViewSet):
    model, serializer_class = Mood, s.MoodAdminSerializer


class OccasionViewSet(TaxonomyViewSet):
    model, serializer_class = Occasion, s.OccasionAdminSerializer


# ── Orders ─────────────────────────────────────────────
class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsStaff]
    pagination_class = AdminPagination
    lookup_field = "order_number"

    def get_serializer_class(self):
        return s.OrderListAdminSerializer if self.action == "list" else s.OrderDetailAdminSerializer

    def filtered(self):
        p = self.request.query_params
        qs = Order.objects.select_related("user").annotate(items_count=Coalesce(Sum("items__quantity"), 0))
        for key in ("status", "payment_status", "payment_method"):
            if p.get(key):
                qs = qs.filter(**{key: p[key]})
        if p.get("search"):
            q = p["search"].strip()
            qs = qs.filter(Q(order_number__icontains=q) | Q(email__icontains=q) | Q(shipping_address__name__icontains=q)
                           | Q(shipping_address__phone__icontains=q) | Q(razorpay_payment_id__icontains=q))
        if p.get("customer"):
            qs = qs.filter(user_id=p["customer"])
        for key, lookup in (("date_from", "created_at__date__gte"), ("date_to", "created_at__date__lte")):
            if p.get(key):
                try:
                    qs = qs.filter(**{lookup: date.fromisoformat(p[key])})
                except ValueError:
                    pass
        ordering = p.get("ordering")
        return qs.order_by(ordering if ordering in {"total", "-total", "created_at", "-created_at"} else "-created_at")

    def get_queryset(self):
        if self.action == "list":
            return self.filtered()
        return Order.objects.select_related("user").prefetch_related("items", "events")

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        counts = dict(Order.objects.values_list("status").annotate(n=Count("id")))
        response.data["status_counts"] = {"all": sum(counts.values()), **counts}
        return response

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        data, who = request.data, actor(request)

        # 1) plain fields first, so a "shipped" email already carries the tracking link
        changed = []
        for field in ("tracking_url", "courier", "admin_note"):
            if field in data and (data[field] or "") != (getattr(order, field) or ""):
                setattr(order, field, data[field] or (None if field == "tracking_url" else ""))
                changed.append(field)
        if "payment_status" in data and data["payment_status"] != order.payment_status:
            if data["payment_status"] not in dict(Order.PAYMENT_STATUS):
                raise ValidationError({"payment_status": ["Unknown payment status."]})
            if data["payment_status"] == "paid" and order.payment_method == "razorpay" and order.payment_status == "pending":
                services._use_coupon(order)
            order.payment_status = data["payment_status"]
            changed.append("payment_status")
            services.log_event(order, f"Payment marked {order.get_payment_status_display().lower()}", who)
        if changed:
            order.full_clean(exclude=["user", "coupon", "order_number"])
            order.save()
            if "tracking_url" in changed and order.tracking_url:
                services.log_event(order, f"Tracking added{f' ({order.courier})' if order.courier else ''}", who)

        # 2) then the status change (emails the customer, releases stock on cancel)
        if "status" in data and data["status"] != order.status:
            if data["status"] not in dict(Order.STATUS):
                raise ValidationError({"status": ["Unknown status."]})
            services.change_status(order, data["status"], who)

        return Response(s.OrderDetailAdminSerializer(self.get_queryset().get(pk=order.pk)).data)

    @action(detail=True, methods=["post"])
    def note(self, request, order_number=None):
        order = self.get_object()
        text = str(request.data.get("message", "")).strip()
        if not text:
            raise ValidationError({"detail": "Write a note first."})
        services.log_event(order, text[:255], actor(request))
        return Response(s.OrderEventSerializer(order.events.all(), many=True).data, status=201)

    @action(detail=False, methods=["get"])
    def export(self, request):
        rows = []
        for o in self.filtered().prefetch_related("items"):
            a = o.shipping_address or {}
            rows.append([
                o.order_number, timezone.localtime(o.created_at).strftime("%Y-%m-%d %H:%M"), a.get("name", ""), o.email,
                a.get("phone", ""), f"{a.get('line1', '')} {a.get('line2', '')}".strip(), a.get("city", ""), a.get("state", ""),
                a.get("pincode", ""), "; ".join(f"{i.quantity}× {i.name}" for i in o.items.all()), o.subtotal, o.discount,
                o.coupon_code or "", o.shipping, o.total, o.payment_method, o.payment_status, o.status, o.tracking_url or "",
            ])
        return csv_response(
            f"orders-{timezone.localdate()}.csv",
            ["Order", "Date", "Name", "Email", "Phone", "Address", "City", "State", "Pincode", "Items", "Subtotal",
             "Discount", "Coupon", "Shipping", "Total", "Payment", "Payment status", "Status", "Tracking"],
            rows,
        )


class CouponViewSet(StaffViewSet):
    serializer_class = s.CouponAdminSerializer
    pagination_class = None

    def get_queryset(self):
        return Coupon.objects.annotate(
            revenue=Coalesce(Sum("orders__total", filter=~Q(orders__status="cancelled")), Value(0))
        ).order_by("-is_active", "-created_at")


# ── People ─────────────────────────────────────────────
class CustomerViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsStaff]
    pagination_class = AdminPagination
    serializer_class = s.CustomerAdminSerializer

    def get_queryset(self):
        p = self.request.query_params
        qs = User.objects.filter(is_staff=False).annotate(
            orders_count=Count("orders", filter=~Q(orders__status="cancelled"), distinct=True),
            total_spent=Coalesce(Sum("orders__total", filter=SPENT), 0),
            last_order_at=Max("orders__created_at"),
        )
        if p.get("search"):
            q = p["search"]
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        if p.get("segment") == "repeat":
            qs = qs.filter(orders_count__gte=2)
        elif p.get("segment") == "no_orders":
            qs = qs.filter(orders_count=0)
        ordering = p.get("ordering")
        allowed = {"-total_spent", "-orders_count", "-date_joined", "name", "-last_order_at"}
        return qs.order_by(ordering if ordering in allowed else "-date_joined")

    def retrieve(self, request, *args, **kwargs):
        customer = self.get_object()
        orders = customer.orders.annotate(items_count=Coalesce(Sum("items__quantity"), 0)).order_by("-created_at")
        last = orders.first()
        return Response({
            **self.get_serializer(customer).data,
            "orders": s.OrderListAdminSerializer(orders, many=True).data,
            "last_address": last.shipping_address if last else None,
            "reviews": customer.review_set.count(),
        })

    @action(detail=False, methods=["get"])
    def export(self, request):
        rows = [[c.name, c.email, c.phone, c.orders_count, c.total_spent, timezone.localtime(c.date_joined).date()]
                for c in self.get_queryset()]
        return csv_response(f"customers-{timezone.localdate()}.csv",
                            ["Name", "Email", "Phone", "Orders", "Total spent", "Joined"], rows)


class StaffUserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOwner]
    serializer_class = s.StaffAdminSerializer
    pagination_class = None

    def get_queryset(self):
        return User.objects.filter(is_staff=True).order_by("-is_superuser", "name")

    def perform_update(self, serializer):
        if serializer.instance == self.request.user and (
            serializer.validated_data.get("is_active") is False or serializer.validated_data.get("is_superuser") is False
        ):
            raise ValidationError({"detail": "You can't remove your own owner access."})
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user == request.user:
            raise ValidationError({"detail": "You can't remove yourself."})
        if user.orders.exists():
            user.is_staff = user.is_superuser = False
            user.save(update_fields=["is_staff", "is_superuser"])
        else:
            user.delete()
        return Response(status=204)


# ── Moderation & inbox ─────────────────────────────────
class ReviewViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsStaff]
    pagination_class = AdminPagination
    serializer_class = s.ReviewAdminSerializer

    def get_queryset(self):
        p = self.request.query_params
        qs = Review.objects.select_related("product")
        if p.get("status") == "visible":
            qs = qs.filter(is_approved=True)
        elif p.get("status") == "hidden":
            qs = qs.filter(is_approved=False)
        if p.get("rating", "").isdigit():
            qs = qs.filter(rating=int(p["rating"]))
        if p.get("search"):
            q = p["search"]
            qs = qs.filter(Q(comment__icontains=q) | Q(user_name__icontains=q) | Q(product__name__icontains=q))
        return qs.order_by("-created_at")


class MessageViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsStaff]
    pagination_class = AdminPagination
    serializer_class = s.MessageAdminSerializer

    def get_queryset(self):
        p = self.request.query_params
        qs = ContactMessage.objects.all()
        if p.get("status") == "open":
            qs = qs.filter(is_resolved=False)
        elif p.get("status") == "resolved":
            qs = qs.filter(is_resolved=True)
        if p.get("search"):
            q = p["search"]
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(message__icontains=q))
        return qs.order_by("is_resolved", "-created_at")


class SubscriberViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsStaff]
    pagination_class = AdminPagination
    serializer_class = s.SubscriberAdminSerializer

    def get_queryset(self):
        qs = NewsletterSubscriber.objects.all()
        if self.request.query_params.get("search"):
            qs = qs.filter(email__icontains=self.request.query_params["search"])
        return qs

    @action(detail=False, methods=["get"])
    def export(self, request):
        rows = [[x.email, "yes" if x.is_active else "no", timezone.localtime(x.created_at).date()] for x in self.get_queryset()]
        return csv_response(f"subscribers-{timezone.localdate()}.csv", ["Email", "Subscribed", "Joined"], rows)


class QuizQuestionViewSet(StaffViewSet):
    serializer_class = s.QuizQuestionAdminSerializer
    pagination_class = None
    queryset = QuizQuestion.objects.all()


class StoreSettingsView(APIView):
    permission_classes = [StaffReadOwnerWrite]

    @extend_schema(responses=s.StoreSettingsSerializer)
    def get(self, request):
        return Response(s.StoreSettingsSerializer(StoreSettings.load()).data)

    @extend_schema(request=s.StoreSettingsSerializer, responses=s.StoreSettingsSerializer)
    def patch(self, request):
        ser = s.StoreSettingsSerializer(StoreSettings.load(), data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


class NavCountsView(APIView):
    """Small badges for the sidebar."""

    permission_classes = [IsStaff]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response({
            "orders": Order.objects.filter(status="processing").count(),
            "messages": ContactMessage.objects.filter(is_resolved=False).count(),
            "reviews": Review.objects.filter(created_at__gte=timezone.now() - timedelta(days=7)).count(),
        })
