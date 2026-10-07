from django.conf import settings
from django.db import models
from django.db.models import Avg, Count
from django.utils.text import slugify


class Taxonomy(models.Model):
    slug = models.SlugField(unique=True, max_length=60)
    name = models.CharField(max_length=80)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Category(Taxonomy):
    description = models.CharField(max_length=200, blank=True)

    class Meta(Taxonomy.Meta):
        verbose_name_plural = "categories"


class Mood(Taxonomy):
    pass


class Occasion(Taxonomy):
    pass


def empty_notes():
    return {"top": [], "middle": [], "base": []}


class Product(models.Model):
    slug = models.SlugField(unique=True, max_length=120)
    name = models.CharField(max_length=120)
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)

    price = models.PositiveIntegerField(help_text="Whole rupees")
    compare_price = models.PositiveIntegerField(null=True, blank=True, help_text="Crossed-out MRP, optional")
    size = models.CharField(max_length=40, default="200g")

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    moods = models.ManyToManyField(Mood, blank=True, related_name="products")
    occasions = models.ManyToManyField(Occasion, blank=True, related_name="products")
    notes = models.JSONField(default=empty_notes, blank=True)

    burn_time_hours = models.PositiveIntegerField(default=45)
    wax_type = models.CharField(max_length=60, default="100% Soy")
    wick_type = models.CharField(max_length=60, default="Cotton")
    fragrance_load = models.CharField(max_length=20, default="10%")

    stock = models.PositiveIntegerField(default=0)
    sku = models.CharField(max_length=40, blank=True)
    color = models.CharField(max_length=9, default="#C99A6B", help_text="Jar colour shown when there is no photo")

    is_active = models.BooleanField(default=True, help_text="Hidden from the store when off")
    is_bestseller = models.BooleanField(default=False)
    is_new = models.BooleanField(default=False)

    # Cached from approved reviews (see refresh_rating)
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=0)
    reviews_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_bestseller", "id"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "candle"
            slug, n = base, 2
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def refresh_rating(self):
        agg = self.reviews.filter(is_approved=True).aggregate(avg=Avg("rating"), n=Count("id"))
        self.rating = round(agg["avg"] or 0, 1)
        self.reviews_count = agg["n"]
        Product.objects.filter(pk=self.pk).update(rating=self.rating, reviews_count=self.reviews_count)


class ProductImage(models.Model):
    """A photo can be an uploaded file or an external URL (e.g. Cloudinary)."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="products/%Y/%m/", blank=True)
    url = models.URLField(blank=True, max_length=500)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def src(self, request=None):
        if self.image:
            return request.build_absolute_uri(self.image.url) if request else self.image.url
        return self.url


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    user_name = models.CharField(max_length=120)
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=160, blank=True)
    comment = models.TextField()
    verified = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True, help_text="Untick to hide from the store")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.rating}★ {self.product} — {self.user_name}"
