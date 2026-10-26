from django.db import transaction
from django.db.models import F
from rest_framework import serializers

from backend.trips.models import Booking
from backend.trips.models import Departure
from backend.trips.models import Destination
from backend.trips.models import Interest
from backend.trips.models import ItineraryDay
from backend.trips.models import Region
from backend.trips.models import Review
from backend.trips.models import Trip
from backend.trips.models import TripPhoto


class RegionSerializer(serializers.ModelSerializer):
    destination = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = Region
        fields = ["slug", "name", "tagline", "image", "destination"]


class DestinationSerializer(serializers.ModelSerializer):
    regions = RegionSerializer(many=True, read_only=True)

    class Meta:
        model = Destination
        fields = ["slug", "name", "tagline", "intro", "image", "regions"]


class InterestSerializer(serializers.ModelSerializer):
    class Meta:
        model = Interest
        fields = ["slug", "name", "description"]


class TripSummarySerializer(serializers.ModelSerializer):
    destination = serializers.SlugRelatedField(
        source="region.destination", slug_field="slug", read_only=True,
    )
    region = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    region_name = serializers.CharField(source="region.name", read_only=True)
    interests = serializers.SlugRelatedField(
        slug_field="slug", many=True, read_only=True,
    )

    class Meta:
        model = Trip
        fields = [
            "slug",
            "title",
            "summary",
            "destination",
            "region",
            "region_name",
            "interests",
            "duration_days",
            "difficulty",
            "max_altitude_m",
            "group_size",
            "best_season",
            "price_from_usd",
            "image",
            "is_bestseller",
        ]


class ItineraryDaySerializer(serializers.ModelSerializer):
    class Meta:
        model = ItineraryDay
        fields = ["day_label", "title", "description"]


class TripPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripPhoto
        fields = ["id", "image", "caption"]


class TripDetailSerializer(TripSummarySerializer):
    highlights = serializers.SerializerMethodField()
    itinerary = ItineraryDaySerializer(many=True, read_only=True)
    photos = TripPhotoSerializer(many=True, read_only=True)
    includes = serializers.SerializerMethodField()
    excludes = serializers.SerializerMethodField()

    class Meta(TripSummarySerializer.Meta):
        fields = [
            *TripSummarySerializer.Meta.fields,
            "highlights",
            "itinerary",
            "photos",
            "includes",
            "excludes",
        ]

    def get_highlights(self, trip):
        return [h.text for h in trip.highlights.all()]

    def get_includes(self, trip):
        return [i.text for i in trip.inclusions.all() if i.kind == i.Kind.INCLUDED]

    def get_excludes(self, trip):
        return [i.text for i in trip.inclusions.all() if i.kind == i.Kind.EXCLUDED]


class DepartureSerializer(serializers.ModelSerializer):
    trip = TripSummarySerializer(read_only=True)
    seats_left = serializers.IntegerField(read_only=True)

    class Meta:
        model = Departure
        fields = ["id", "trip", "start_date", "price_usd", "seats_left"]


class BookingSerializer(serializers.ModelSerializer):
    departure = serializers.PrimaryKeyRelatedField(queryset=Departure.objects.all())

    class Meta:
        model = Booking
        fields = [
            "id",
            "departure",
            "lead_name",
            "email",
            "phone",
            "travellers",
            "message",
            "total_usd",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "total_usd", "status", "created_at"]

    def validate_travellers(self, value):
        if value > 20:
            raise serializers.ValidationError(
                "For groups larger than 20, please contact us directly.",
            )
        return value

    @transaction.atomic
    def create(self, validated_data):
        # Lock the departure row so two people can't book the last seats at once.
        departure = Departure.objects.select_for_update().get(
            pk=validated_data["departure"].pk,
        )
        travellers = validated_data["travellers"]
        if not departure.is_open:
            raise serializers.ValidationError(
                {"departure": "This departure is no longer taking bookings."},
            )
        if travellers > departure.seats_left:
            raise serializers.ValidationError(
                {
                    "travellers": f"Only {departure.seats_left} seats left on this departure.",
                },
            )
        Departure.objects.filter(pk=departure.pk).update(
            seats_booked=F("seats_booked") + travellers,
        )
        request = self.context.get("request")
        user = request.user if request and request.user.is_authenticated else None
        return Booking.objects.create(
            **{**validated_data, "departure": departure},
            user=user,
            total_usd=departure.price_usd * travellers,
        )


class ReviewSerializer(serializers.ModelSerializer):
    trip = serializers.SlugRelatedField(
        slug_field="slug", queryset=Trip.objects.filter(is_published=True),
    )
    trip_title = serializers.CharField(source="trip.title", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "trip",
            "trip_title",
            "name",
            "country",
            "rating",
            "title",
            "body",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        # New reviews wait for moderation in the admin before going live.
        request = self.context.get("request")
        user = request.user if request and request.user.is_authenticated else None
        return Review.objects.create(**validated_data, user=user, is_published=False)
