from rest_framework import serializers
from drf_spectacular.utils import OpenApiTypes, extend_schema_field

from .models import Category, Mood, Occasion, Product, Review


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "slug", "name", "description"]


class MoodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mood
        fields = ["id", "slug", "name"]


class OccasionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Occasion
        fields = ["id", "slug", "name"]


def product_images(product, request):
    return [src for src in (p.src(request) for p in product.photos.all()) if src]


class ProductSerializer(serializers.ModelSerializer):
    """Exact shape from API_CONTRACT.md."""

    category = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    moods = serializers.SlugRelatedField(slug_field="slug", many=True, read_only=True)
    occasions = serializers.SlugRelatedField(slug_field="slug", many=True, read_only=True)
    rating = serializers.FloatField(read_only=True)
    images = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "slug", "name", "tagline", "description", "price", "compare_price", "size",
            "category", "moods", "occasions", "notes", "burn_time_hours", "wax_type", "wick_type",
            "fragrance_load", "stock", "rating", "reviews_count", "is_bestseller", "is_new", "color", "images",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_images(self, obj):
        return product_images(obj, self.context.get("request"))


class ReviewSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(read_only=True)
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["id", "product_id", "user_name", "rating", "title", "comment", "created_at", "verified"]
        read_only_fields = ["user_name", "verified"]

    @extend_schema_field(OpenApiTypes.DATE)
    def get_created_at(self, obj):
        return obj.created_at.date().isoformat()

    def validate_rating(self, v):
        if not 1 <= v <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return v
