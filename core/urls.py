from django.urls import path, re_path

from . import views

urlpatterns = [
    path("", views.api_root, name="api-index"),
    path("contact/", views.ContactView.as_view()),
    path("newsletter/", views.NewsletterView.as_view()),
    path("quiz/", views.QuizView.as_view()),
    path("quiz/recommend/", views.QuizRecommendView.as_view()),
    re_path(r"^pincode/(?P<pincode>\d{6})/$", views.PincodeView.as_view()),
]
