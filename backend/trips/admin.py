from django.contrib import admin
from django.contrib import messages
from django.db import transaction
from django.db.models import F

from .models import Booking
from .models import Departure
from .models import Destination
from .models import Interest
from .models import ItineraryDay
from .models import Region
from .models import Review
from .models import Trip
from .models import TripHighlight
from .models import TripInclusion
from .models import TripPhoto


class RegionInline(admin.TabularInline):
    model = Region
    extra = 0
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "order"]
    list_editable = ["order"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [RegionInline]


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ["name", "destination", "order"]
    list_editable = ["order"]
    list_filter = ["destination"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Interest)
class InterestAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "order"]
    list_editable = ["order"]
    prepopulated_fields = {"slug": ("name",)}


class TripHighlightInline(admin.TabularInline):
    model = TripHighlight
    extra = 0


class TripPhotoInline(admin.TabularInline):
    model = TripPhoto
    extra = 1
    fields = ["image", "caption", "order"]


class ItineraryDayInline(admin.StackedInline):
    model = ItineraryDay
    extra = 0


class TripInclusionInline(admin.TabularInline):
    model = TripInclusion
    extra = 0


class DepartureInline(admin.TabularInline):
    model = Departure
    extra = 0
    fields = ["start_date", "price_usd", "seats_total", "seats_booked", "is_open"]


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "region",
        "duration_days",
        "difficulty",
        "price_from_usd",
        "is_bestseller",
        "is_published",
    ]
    list_editable = ["is_bestseller", "is_published"]
    list_filter = ["region", "difficulty", "interests", "is_published"]
    search_fields = ["title", "summary"]
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ["interests"]
    inlines = [
        TripHighlightInline,
        TripPhotoInline,
        ItineraryDayInline,
        TripInclusionInline,
        DepartureInline,
    ]


@admin.register(Departure)
class DepartureAdmin(admin.ModelAdmin):
    list_display = [
        "trip",
        "start_date",
        "price_usd",
        "seats_total",
        "seats_booked",
        "seats_left",
        "is_open",
    ]
    list_filter = ["is_open", "trip__region"]
    date_hierarchy = "start_date"
    search_fields = ["trip__title"]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        "lead_name",
        "email",
        "departure",
        "travellers",
        "total_usd",
        "status",
        "created_at",
    ]
    list_filter = ["status", "departure__trip"]
    search_fields = ["lead_name", "email", "phone"]
    readonly_fields = ["total_usd", "created_at", "user"]
    actions = ["confirm_bookings", "cancel_bookings"]

    @admin.action(description="Confirm selected bookings")
    def confirm_bookings(self, request, queryset):
        updated = queryset.filter(status=Booking.Status.PENDING).update(
            status=Booking.Status.CONFIRMED,
        )
        self.message_user(request, f"{updated} booking(s) confirmed.", messages.SUCCESS)

    @admin.action(description="Cancel selected bookings (releases seats)")
    def cancel_bookings(self, request, queryset):
        count = 0
        with transaction.atomic():
            for booking in queryset.exclude(
                status=Booking.Status.CANCELLED,
            ).select_for_update():
                Departure.objects.filter(pk=booking.departure_id).update(
                    seats_booked=F("seats_booked") - booking.travellers,
                )
                booking.status = Booking.Status.CANCELLED
                booking.save(update_fields=["status"])
                count += 1
        self.message_user(
            request,
            f"{count} booking(s) cancelled and seats released.",
            messages.SUCCESS,
        )


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["title", "name", "trip", "rating", "is_published", "created_at"]
    list_editable = ["is_published"]
    list_filter = ["is_published", "rating", "trip__region__destination", "trip"]
    search_fields = ["name", "title", "body", "trip__title"]
    readonly_fields = ["created_at", "user"]
    actions = ["publish_reviews", "unpublish_reviews"]

    @admin.action(description="Publish selected reviews")
    def publish_reviews(self, request, queryset):
        updated = queryset.update(is_published=True)
        self.message_user(request, f"{updated} review(s) published.", messages.SUCCESS)

    @admin.action(description="Unpublish selected reviews")
    def unpublish_reviews(self, request, queryset):
        updated = queryset.update(is_published=False)
        self.message_user(request, f"{updated} review(s) hidden.", messages.SUCCESS)
