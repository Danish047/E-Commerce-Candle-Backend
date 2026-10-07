from django.urls import path

from . import views

urlpatterns = [
    path("products/", views.ProductListView.as_view()),
    path("products/<slug:slug>/related/", views.RelatedProductsView.as_view()),
    path("products/<slug:slug>/reviews/", views.ProductReviewsView.as_view()),
    path("products/<slug:slug>/", views.ProductDetailView.as_view()),
    path("categories/", views.CategoryList.as_view()),
    path("moods/", views.MoodList.as_view()),
    path("occasions/", views.OccasionList.as_view()),
]
