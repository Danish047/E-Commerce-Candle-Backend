from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

router = DefaultRouter(trailing_slash=True)
router.register("products", views.ProductViewSet, basename="admin-products")
router.register("categories", views.CategoryViewSet, basename="admin-categories")
router.register("moods", views.MoodViewSet, basename="admin-moods")
router.register("occasions", views.OccasionViewSet, basename="admin-occasions")
router.register("orders", views.OrderViewSet, basename="admin-orders")
router.register("coupons", views.CouponViewSet, basename="admin-coupons")
router.register("customers", views.CustomerViewSet, basename="admin-customers")
router.register("staff", views.StaffUserViewSet, basename="admin-staff")
router.register("reviews", views.ReviewViewSet, basename="admin-reviews")
router.register("messages", views.MessageViewSet, basename="admin-messages")
router.register("subscribers", views.SubscriberViewSet, basename="admin-subscribers")
router.register("quiz", views.QuizQuestionViewSet, basename="admin-quiz")

urlpatterns = [
    path("auth/login/", views.AdminLoginView.as_view()),
    path("auth/refresh/", TokenRefreshView.as_view()),
    path("auth/me/", views.AdminMeView.as_view()),
    path("auth/password/", views.ChangePasswordView.as_view()),
    path("dashboard/", views.DashboardView.as_view()),
    path("search/", views.SearchView.as_view()),
    path("nav-counts/", views.NavCountsView.as_view()),
    path("settings/", views.StoreSettingsView.as_view()),
] + router.urls
