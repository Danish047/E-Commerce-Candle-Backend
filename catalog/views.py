from django.db.models import Q, TextField
from django.db.models.functions import Cast
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .models import Category, Mood, Occasion, Product, Review
from .serializers import CategorySerializer, MoodSerializer, OccasionSerializer, ProductSerializer, ReviewSerializer


class StorePagination(PageNumberPagination):
    """Contract: next/previous are page numbers, not URLs."""

    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 60

    def get_paginated_response(self, data):
        return Response({
            "count": self.page.paginator.count,
            "next": self.page.next_page_number() if self.page.has_next() else None,
            "previous": self.page.previous_page_number() if self.page.has_previous() else None,
            "results": data,
        })


def live_products():
    return (
        Product.objects.filter(is_active=True)
        .select_related("category")
        .prefetch_related("moods", "occasions", "photos")
    )


ORDERINGS = {"price": "price", "-price": "-price", "-rating": "-rating", "-reviews_count": "-reviews_count", "-id": "-id"}


class ProductListView(generics.ListAPIView):
    serializer_class = ProductSerializer
    pagination_class = StorePagination

    def get_queryset(self):
        p = self.request.query_params
        qs = live_products()
        if p.get("category"):
            qs = qs.filter(category__slug=p["category"])
        if p.get("mood"):
            qs = qs.filter(moods__slug=p["mood"])
        if p.get("occasion"):
            qs = qs.filter(occasions__slug=p["occasion"])
        for key, lookup in (("min_price", "price__gte"), ("max_price", "price__lte")):
            if p.get(key, "").isdigit():
                qs = qs.filter(**{lookup: int(p[key])})
        if p.get("is_bestseller") == "true":
            qs = qs.filter(is_bestseller=True)
        if p.get("is_new") == "true":
            qs = qs.filter(is_new=True)
        if p.get("search"):
            q = p["search"].strip()
            qs = qs.annotate(notes_text=Cast("notes", TextField())).filter(
                Q(name__icontains=q) | Q(tagline__icontains=q) | Q(description__icontains=q) | Q(notes_text__icontains=q)
            )
        qs = qs.distinct()
        if p.get("ordering") in ORDERINGS:
            qs = qs.order_by(ORDERINGS[p["ordering"]], "id")
        return qs


class ProductDetailView(generics.RetrieveAPIView):
    serializer_class = ProductSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return live_products()


class RelatedProductsView(APIView):
    @extend_schema(responses=ProductSerializer(many=True))
    def get(self, request, slug):
        product = get_object_or_404(live_products(), slug=slug)
        qs = (
            live_products()
            .exclude(pk=product.pk)
            .filter(Q(category=product.category) | Q(moods__in=product.moods.all()))
            .distinct()[:4]
        )
        return Response(ProductSerializer(qs, many=True, context={"request": request}).data)


class ProductReviewsView(APIView):
    def get_permissions(self):
        return [IsAuthenticated()] if self.request.method == "POST" else []

    @extend_schema(responses=ReviewSerializer(many=True))
    def get(self, request, slug):
        product = get_object_or_404(Product, slug=slug, is_active=True)
        reviews = product.reviews.filter(is_approved=True)
        return Response(ReviewSerializer(reviews, many=True).data)

    @extend_schema(request=ReviewSerializer, responses={201: ReviewSerializer})
    def post(self, request, slug):
        from orders.models import OrderItem

        product = get_object_or_404(Product, slug=slug, is_active=True)
        if not request.data.get("comment"):
            raise ValidationError({"detail": "Rating and comment are required."})
        s = ReviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        verified = OrderItem.objects.filter(
            order__user=request.user, product=product, order__payment_status__in=["paid", "pending"]
        ).exclude(order__status="cancelled").exists()
        review = s.save(product=product, user=request.user, user_name=request.user.name, verified=verified)
        return Response(ReviewSerializer(review).data, status=201)


class CategoryList(generics.ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    pagination_class = None


class MoodList(generics.ListAPIView):
    queryset = Mood.objects.all()
    serializer_class = MoodSerializer
    pagination_class = None


class OccasionList(generics.ListAPIView):
    queryset = Occasion.objects.all()
    serializer_class = OccasionSerializer
    pagination_class = None
