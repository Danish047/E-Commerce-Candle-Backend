from django.contrib import admin

from .models import Category, Mood, Occasion, Product, ProductImage, Review


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "price", "stock", "is_active", "is_bestseller", "rating", "reviews_count"]
    list_filter = ["is_active", "is_bestseller", "is_new", "category"]
    list_editable = ["price", "stock", "is_active"]
    search_fields = ["name", "tagline", "sku"]
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ["moods", "occasions"]
    inlines = [ProductImageInline]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["product", "user_name", "rating", "verified", "is_approved", "created_at"]
    list_filter = ["is_approved", "verified", "rating"]
    list_editable = ["is_approved"]
    search_fields = ["user_name", "comment", "product__name"]


for model in (Category, Mood, Occasion):
    admin.site.register(model, list_display=["name", "slug", "sort_order"], prepopulated_fields={"slug": ("name",)})
