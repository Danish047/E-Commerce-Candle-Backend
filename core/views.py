import re

from django.http import JsonResponse
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiTypes, extend_schema

from catalog.serializers import ProductSerializer
from catalog.views import live_products

from . import emails
from .models import ContactMessage, NewsletterSubscriber, QuizQuestion, StoreSettings


def api_root(request):
    return JsonResponse({"service": "Lumière & Co. API", "status": "ok"})


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["name", "email", "phone", "topic", "message"]


class ContactView(APIView):
    throttle_scope = "contact"

    @extend_schema(request=ContactSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        s = ContactSerializer(data=request.data)
        if not s.is_valid():
            raise ValidationError({"detail": "Please fill in all required fields."})
        emails.contact_received(s.save())
        return Response({"detail": "Thanks! We will get back to you within 24 hours."})


class NewsletterView(APIView):
    throttle_scope = "contact"

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        email = str(request.data.get("email", "")).strip().lower()
        if not re.match(r"^\S+@\S+\.\S+$", email):
            raise ValidationError({"detail": "Enter a valid email."})
        sub, _ = NewsletterSubscriber.objects.get_or_create(email=email)
        if not sub.is_active:
            sub.is_active = True
            sub.save(update_fields=["is_active"])
        return Response({"detail": "You're on the list! Check your inbox for 10% off."})


class QuizView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response({
            "questions": [
                {"id": q.key, "question": q.question, "options": q.options} for q in QuizQuestion.objects.all()
            ]
        })


class QuizRecommendView(APIView):
    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        answers = request.data.get("answers") or {}
        mood, category, occasion = answers.get("mood"), answers.get("category"), answers.get("occasion")
        scored = []
        for p in live_products().exclude(category__slug="gift-sets").filter(stock__gt=0):
            moods = {m.slug for m in p.moods.all()}
            occasions = {o.slug for o in p.occasions.all()}
            score = (3 if mood in moods else 0) + (3 if p.category.slug == category else 0)
            score += (2 if occasion in occasions else 0) + float(p.rating) / 10
            scored.append((score, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [p for _, p in scored[:3]]
        return Response({"products": ProductSerializer(top, many=True, context={"request": request}).data})


class PincodeView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pincode):
        return Response(StoreSettings.load().pincode_info(pincode))
