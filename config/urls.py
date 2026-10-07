from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from core.views import api_root

admin.site.site_header = "Lumière & Co. — Django admin"
admin.site.site_title = "Lumière admin"
admin.site.index_title = "Store data"

urlpatterns = [
    path("", api_root, name="api-root"),
    re_path(r"^admin/?$", lambda request: redirect("/django-admin/"), name="admin-shortcut"),
    path("django-admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Storefront API (see API_CONTRACT.md in the frontend)
    path("api/", include("accounts.urls")),
    path("api/", include("catalog.urls")),
    path("api/", include("orders.urls")),
    path("api/", include("core.urls")),
    # Admin panel API (staff only)
    path("api/admin/", include("adminpanel.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
