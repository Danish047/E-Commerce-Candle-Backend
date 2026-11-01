"""Put every existing product and category under a 'Candles' section and add a
'3D Printing' section (Coming soon) so the owner can switch it live from the admin panel."""
from django.db import migrations

CANDLES = {
    "slug": "candles", "name": "Candles", "icon": "🕯️", "sort_order": 1, "product_type": "candle",
    "tagline": "Hand-poured soy candles that smell like home",
    "description": "Small-batch soy wax candles in jars, tins and sculpted shapes, from kesar kulfi to mogra.",
    "accent_color": "#F3E2CF", "status": "live",
}
PRINTING = {
    "slug": "3d-printing", "name": "3D Printing", "icon": "🖨️", "sort_order": 2, "product_type": "general",
    "tagline": "Custom 3D printed models, gifts and decor",
    "description": "Name plates, figurines, keychains, home decor and spare parts, printed to order. "
                   "Send us your idea or file and we will share a quote.",
    "accent_color": "#DCE6F2", "status": "coming_soon", "allow_custom_orders": True,
    "spec_fields": ["Material", "Colour", "Dimensions", "Finish"],
}


def forwards(apps, schema_editor):
    Section = apps.get_model("catalog", "Section")
    Category = apps.get_model("catalog", "Category")
    Product = apps.get_model("catalog", "Product")

    candles, _ = Section.objects.get_or_create(slug=CANDLES["slug"], defaults=CANDLES)
    printing, _ = Section.objects.get_or_create(slug=PRINTING["slug"], defaults=PRINTING)
    Category.objects.filter(section__isnull=True).update(section=candles)
    Product.objects.filter(section__isnull=True).update(section=candles)
    Category.objects.get_or_create(
        slug="3d-models",
        defaults={"name": "3D Models", "description": "Printed to order", "section": printing, "sort_order": 100},
    )


def backwards(apps, schema_editor):
    apps.get_model("catalog", "Product").objects.update(section=None)
    apps.get_model("catalog", "Category").objects.filter(slug="3d-models", products__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("catalog", "0002_sections")]
    operations = [migrations.RunPython(forwards, backwards)]
