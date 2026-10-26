from django.db.models import Avg
from django.db.models import Prefetch
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from backend.trips.models import Booking
from backend.trips.models import Departure
from backend.trips.models import Destination
from backend.trips.models import Interest
from backend.trips.models import Region
from backend.trips.models import Review
from backend.trips.models import Trip

from .serializers import BookingSerializer
from .serializers import DepartureSerializer
from .serializers import DestinationSerializer
from .serializers import InterestSerializer
from .serializers import RegionSerializer
from .serializers import ReviewSerializer
from .serializers import TripDetailSerializer
from .serializers import TripSummarySerializer


class StandardPagination(PageNumberPagination):
    """Matches the frontend's IResponseApi<T> shape."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.page.paginator.count,
                "current_page": self.page.number,
                "page_size": self.get_page_size(self.request),
                "total_pages": self.page.paginator.num_pages,
                "results": data,
            },
        )


DURATION_FILTERS = {
    "day": Q(duration_days=1),
    "2-3": Q(duration_days__range=(2, 3)),
    "4-7": Q(duration_days__range=(4, 7)),
    "8-14": Q(duration_days__range=(8, 14)),
    "15-plus": Q(duration_days__gte=15),
    "bestsellers": Q(is_bestseller=True),
}

TRIP_SORTS = {
    "price-asc": ["price_from_usd"],
    "price-desc": ["-price_from_usd"],
    "duration": ["duration_days", "title"],
}


class DestinationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Destination.objects.prefetch_related("regions")
    serializer_class = DestinationSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
    pagination_class = None


class RegionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Region.objects.select_related("destination")
    serializer_class = RegionSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
    pagination_class = None


class InterestViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Interest.objects.all()
    serializer_class = InterestSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
    pagination_class = None


class TripViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Published trips. Filters: ?destination=, ?region=, ?interest=,
    ?duration=day|2-3|4-7|8-14|15-plus|bestsellers, ?sort=price-asc|price-desc|duration
    """

    permission_classes = [AllowAny]
    lookup_field = "slug"
    pagination_class = StandardPagination
    filter_backends = []  # filtering is explicit below

    def get_serializer_class(self):
        return (
            TripDetailSerializer if self.action == "retrieve" else TripSummarySerializer
        )

    def get_queryset(self):
        qs = (
            Trip.objects.filter(is_published=True)
            .select_related("region__destination")
            .prefetch_related("interests")
        )
        if self.action == "retrieve":
            return qs.prefetch_related(
                "highlights", "itinerary", "photos", "inclusions",
            )

        params = self.request.query_params
        if destination := params.get("destination"):
            qs = qs.filter(region__destination__slug=destination)
        if region := params.get("region"):
            qs = qs.filter(region__slug=region)
        if interest := params.get("interest"):
            qs = qs.filter(interests__slug=interest)
        if (duration := params.get("duration")) in DURATION_FILTERS:
            qs = qs.filter(DURATION_FILTERS[duration])
        return qs.distinct().order_by(
            *TRIP_SORTS.get(params.get("sort", ""), ["-is_bestseller", "title"]),
        )


class DepartureViewSet(viewsets.ReadOnlyModelViewSet):
    """Upcoming open departures. Filter with ?trip=<slug>."""

    serializer_class = DepartureSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = (
            Departure.objects.filter(
                is_open=True,
                trip__is_published=True,
                start_date__gte=timezone.localdate(),
            )
            .select_related("trip__region__destination")
            .prefetch_related(Prefetch("trip__interests"))
        )
        if trip := self.request.query_params.get("trip"):
            qs = qs.filter(trip__slug=trip)
        return qs


class BookingViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Create a booking request. Seats are held while the booking is pending."""

    queryset = Booking.objects.none()
    serializer_class = BookingSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "booking"


class ReviewViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet,
):
    """
    Published reviews. Filter with ?trip=<slug> or ?destination=<slug>.
    POST submits a review for moderation; it is hidden until published in the admin.
    """

    serializer_class = ReviewSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination
    filter_backends = []
    throttle_scope = "review"

    def get_throttles(self):
        # Only rate-limit submissions; listing is hit on every page render.
        return [ScopedRateThrottle()] if self.action == "create" else []

    def get_queryset(self):
        qs = Review.objects.filter(
            is_published=True, trip__is_published=True,
        ).select_related("trip")
        params = self.request.query_params
        if trip := params.get("trip"):
            qs = qs.filter(trip__slug=trip)
        if destination := params.get("destination"):
            qs = qs.filter(trip__region__destination__slug=destination)
        return qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        average = self.get_queryset().aggregate(avg=Avg("rating"))["avg"]
        response.data["average_rating"] = round(average, 1) if average else None
        return response
