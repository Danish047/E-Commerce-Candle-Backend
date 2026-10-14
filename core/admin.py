from django.contrib import admin

from .models import Announcement, Banner, ContactMessage, NewsletterSubscriber, QuizQuestion, StoreSettings


@admin.register(StoreSettings)
class StoreSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not StoreSettings.objects.exists()


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "topic", "is_resolved", "created_at"]
    list_filter = ["is_resolved", "topic"]
    list_editable = ["is_resolved"]
    search_fields = ["name", "email", "message"]


admin.site.register(NewsletterSubscriber, list_display=["email", "is_active", "created_at"], search_fields=["email"])
admin.site.register(QuizQuestion, list_display=["key", "question", "sort_order"])


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ["text", "is_active", "start_at", "end_at", "sort_order"]
    list_editable = ["is_active", "sort_order"]


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ["title", "placement", "is_active", "start_at", "end_at", "sort_order"]
    list_filter = ["placement", "is_active"]
    list_editable = ["is_active", "sort_order"]
