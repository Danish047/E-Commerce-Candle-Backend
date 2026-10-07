from django.urls import path

from . import views

urlpatterns = [
    path("coupons/validate/", views.CouponValidateView.as_view()),
    path("orders/", views.OrderListCreateView.as_view()),
    path("orders/<str:order_number>/", views.OrderDetailView.as_view()),
    path("payments/verify/", views.PaymentVerifyView.as_view()),
    path("payments/webhook/", views.RazorpayWebhookView.as_view()),
]
