from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiTypes, extend_schema

from .serializers import LoginSerializer, RegisterSerializer, UserSerializer, tokens_for


class RegisterView(APIView):
    throttle_scope = "auth"

    @extend_schema(request=RegisterSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()
        return Response(tokens_for(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    throttle_scope = "auth"

    @extend_schema(request=LoginSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        s = LoginSerializer(data=request.data, context={"request": request})
        if not s.is_valid():
            raise AuthenticationFailed("Invalid email or password.")
        return Response(tokens_for(s.validated_data["user"]))


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @extend_schema(request=UserSerializer, responses=UserSerializer)
    def patch(self, request):
        s = UserSerializer(request.user, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)
