"""End-to-end API tests: storefront contract + admin panel.

    python manage.py test
"""
import hashlib
import hmac
import json
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from catalog.models import Product
from orders.models import Coupon, Order


class StoreFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_store", "--owner", "owner@test.in", "--password", "Owner@1234", verbosity=0)

    def setUp(self):
        self.c = APIClient()

    def test_api_root(self):
        expected = {"service": "Lumière & Co. API", "status": "ok"}
        for url in ["/", "/api/"]:
            with self.subTest(url=url):
                r = self.c.get(url)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json(), expected)

    def test_admin_shortcut_redirects_to_django_admin(self):
        for url in ["/admin", "/admin/"]:
            with self.subTest(url=url):
                response = self.c.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], "/django-admin/")

    def test_openapi_schema_and_documentation(self):
        schema_response = self.c.get("/api/schema/?format=json")
        self.assertEqual(schema_response.status_code, 200)
        schema = json.loads(schema_response.content)
        paths = schema["paths"]
        self.assertIn("jwtAuth", schema["components"]["securitySchemes"])
        for endpoint in ["/api/auth/login/", "/api/products/", "/api/orders/", "/api/admin/dashboard/"]:
            self.assertIn(endpoint, paths)
        self.assertEqual(self.c.get("/api/docs/").status_code, 200)
        self.assertEqual(self.c.get("/api/redoc/").status_code, 200)

    def register(self, email="priya@test.in"):
        r = self.c.post("/api/auth/register/", {"name": "Priya", "email": email, "password": "secret123"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        return r.data

    def address(self):
        return {"name": "Priya", "phone": "9999999999", "line1": "12 MG Road", "line2": "", "city": "Indore",
                "state": "Madhya Pradesh", "pincode": "452001"}

    def test_catalog_contract(self):
        r = self.c.get("/api/products/", {"category": "spicy", "ordering": "-price", "page_size": 2})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {"count", "next", "previous", "results"})
        p = r.data["results"][0]
        for key in ["slug", "notes", "moods", "occasions", "images", "rating", "compare_price", "color"]:
            self.assertIn(key, p)
        self.assertEqual(self.c.get(f"/api/products/{p['slug']}/").status_code, 200)
        self.assertEqual(self.c.get("/api/products/does-not-exist/").status_code, 404)
        self.assertTrue(self.c.get("/api/products/", {"search": "cardamom"}).data["count"] >= 1)
        self.assertEqual(len(self.c.get("/api/categories/").data), 6)
        self.assertEqual(len(self.c.get("/api/quiz/").data["questions"]), 3)
        rec = self.c.post("/api/quiz/recommend/", {"answers": {"mood": "cosy", "category": "spicy", "occasion": "diwali"}}, format="json")
        self.assertEqual(len(rec.data["products"]), 3)

    def test_coupons(self):
        r = self.c.post("/api/coupons/validate/", {"code": "welcome10", "subtotal": 1798}, format="json")
        self.assertEqual(r.data, {"valid": True, "code": "WELCOME10", "discount": 180, "message": "10% off your first order"})
        r = self.c.post("/api/coupons/validate/", {"code": "FLAT150", "subtotal": 500}, format="json")
        self.assertFalse(r.data["valid"])
        self.assertIn("more", r.data["message"])

    def test_cod_order_and_review(self):
        self.register()
        p = Product.objects.get(slug="monsoon-chai")
        start = p.stock
        r = self.c.post("/api/orders/", {
            "items": [{"product_id": p.id, "quantity": 2}], "shipping_address": self.address(),
            "coupon_code": "WELCOME10", "payment_method": "cod",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        o = r.data["order"]
        self.assertIsNone(r.data["razorpay"])
        self.assertEqual((o["subtotal"], o["discount"], o["shipping"], o["total"]), (1798, 180, 0, 1618))
        self.assertEqual(o["status"], "processing")
        p.refresh_from_db()
        self.assertEqual(p.stock, start - 2)
        self.assertEqual(Coupon.objects.get(code="WELCOME10").times_used, 1)
        self.assertEqual(len(self.c.get("/api/orders/").data), 1)
        self.assertEqual(self.c.get(f"/api/orders/{o['order_number']}/").status_code, 200)
        rv = self.c.post(f"/api/products/{p.slug}/reviews/", {"rating": 5, "comment": "Lovely"}, format="json")
        self.assertEqual(rv.status_code, 201)
        self.assertTrue(rv.data["verified"])

    def test_stock_limit(self):
        p = Product.objects.get(slug="monsoon-chai")
        r = self.c.post("/api/orders/", {"items": [{"product_id": p.id, "quantity": p.stock + 1}],
                                         "shipping_address": self.address(), "email": "g@x.in", "payment_method": "cod"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("left", r.data["detail"])

    @override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET="secret")
    def test_razorpay_flow(self):
        p = Product.objects.get(slug="goa-sunset")
        with mock.patch("razorpay.Client") as client:
            client.return_value.order.create.return_value = {"id": "order_ABC"}
            r = self.c.post("/api/orders/", {"items": [{"product_id": p.id, "quantity": 1}], "shipping_address": self.address(),
                                             "email": "guest@x.in", "payment_method": "razorpay"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["razorpay"]["amount"], (799 + 79) * 100)
        num = r.data["order"]["order_number"]
        bad = self.c.post("/api/payments/verify/", {"order_number": num, "razorpay_order_id": "order_ABC",
                                                    "razorpay_payment_id": "pay_1", "razorpay_signature": "nope"}, format="json")
        self.assertEqual(bad.status_code, 400)
        sig = hmac.new(b"secret", b"order_ABC|pay_1", hashlib.sha256).hexdigest()
        ok = self.c.post("/api/payments/verify/", {"order_number": num, "razorpay_order_id": "order_ABC",
                                                   "razorpay_payment_id": "pay_1", "razorpay_signature": sig}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual((ok.data["order"]["payment_status"], ok.data["order"]["status"]), ("paid", "processing"))

    def test_online_payment_without_keys(self):
        p = Product.objects.first()
        r = self.c.post("/api/orders/", {"items": [{"product_id": p.id, "quantity": 1}], "shipping_address": self.address(),
                                         "email": "g@x.in", "payment_method": "razorpay"}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(Order.objects.count(), 0)  # rolled back, stock untouched


class AdminPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_store", "--owner", "owner@test.in", "--password", "Owner@1234", verbosity=0)

    def setUp(self):
        self.c = APIClient()
        r = self.c.post("/api/admin/auth/login/", {"email": "owner@test.in", "password": "Owner@1234"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["user"]["role"], "owner")
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    def test_customer_cannot_use_admin(self):
        c = APIClient()
        c.post("/api/auth/register/", {"name": "A", "email": "a@x.in", "password": "secret123"}, format="json")
        r = c.post("/api/admin/auth/login/", {"email": "a@x.in", "password": "secret123"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(APIClient().get("/api/admin/dashboard/").status_code, 401)

    def test_dashboard_and_lists(self):
        for url in ["dashboard/?days=7", "products/", "orders/", "customers/", "coupons/", "reviews/", "messages/",
                    "subscribers/", "categories/", "moods/", "occasions/", "quiz/", "settings/", "staff/", "nav-counts/",
                    "search/?q=chai"]:
            r = self.c.get(f"/api/admin/{url}")
            self.assertEqual(r.status_code, 200, f"{url}: {r.content[:200]}")
        self.assertEqual(len(self.c.get("/api/admin/dashboard/?days=7").data["series"]), 7)

    def test_product_crud(self):
        cat = self.c.get("/api/admin/categories/").data[0]["id"]
        r = self.c.post("/api/admin/products/", {"name": "Rose Chai", "price": 699, "category": cat, "stock": 5,
                                                 "color": "#AA5566", "notes": {"top": "Rose, Tea", "middle": [], "base": []}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["slug"], "rose-chai")
        self.assertEqual(r.data["notes"]["top"], ["Rose", "Tea"])
        pid = r.data["id"]
        self.assertEqual(self.c.post(f"/api/admin/products/{pid}/images/", {"url": "https://example.com/a.jpg"}).status_code, 201)
        self.assertEqual(self.c.patch(f"/api/admin/products/{pid}/", {"compare_price": 600}, format="json").status_code, 400)
        self.assertEqual(self.c.post(f"/api/admin/products/{pid}/duplicate/").status_code, 201)
        self.assertEqual(self.c.delete(f"/api/admin/products/{pid}/").status_code, 204)

    def test_order_status_releases_stock(self):
        p = Product.objects.get(slug="monsoon-chai")
        start = p.stock
        store = APIClient()
        r = store.post("/api/orders/", {"items": [{"product_id": p.id, "quantity": 3}], "email": "g@x.in", "payment_method": "cod",
                                        "shipping_address": {"name": "G", "phone": "9", "line1": "x", "city": "y", "state": "z", "pincode": "452001"}},
                       format="json")
        num = r.data["order"]["order_number"]
        up = self.c.patch(f"/api/admin/orders/{num}/", {"status": "shipped", "tracking_url": "https://track.example/1", "courier": "Delhivery"}, format="json")
        self.assertEqual(up.status_code, 200, up.content)
        self.assertEqual(up.data["status"], "shipped")
        cancel = self.c.patch(f"/api/admin/orders/{num}/", {"status": "cancelled"}, format="json")
        self.assertEqual(cancel.data["status"], "cancelled")
        p.refresh_from_db()
        self.assertEqual(p.stock, start)
        self.assertEqual(self.c.patch(f"/api/admin/orders/{num}/", {"status": "processing"}, format="json").status_code, 400)
        self.assertGreaterEqual(len(cancel.data["events"]), 3)
        self.assertEqual(self.c.get("/api/admin/orders/export/").status_code, 200)

    def test_staff_management(self):
        r = self.c.post("/api/admin/staff/", {"name": "Asha", "email": "asha@test.in", "password": "helper123"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        helper = APIClient()
        tok = helper.post("/api/admin/auth/login/", {"email": "asha@test.in", "password": "helper123"}, format="json").data["access"]
        helper.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
        self.assertEqual(helper.get("/api/admin/settings/").status_code, 200)
        self.assertEqual(helper.patch("/api/admin/settings/", {"shipping_fee": 1}, format="json").status_code, 403)
        self.assertEqual(helper.get("/api/admin/staff/").status_code, 403)
