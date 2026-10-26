from django.conf import settings
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F
from django.utils.translation import gettext_lazy as _


class OrderedModel(models.Model):
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ["order", "id"]


class Destination(OrderedModel):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    tagline = models.CharField(max_length=200, blank=True)
    intro = models.TextField(blank=True)
    image = models.ImageField(upload_to="destinations/", blank=True)

    class Meta(OrderedModel.Meta):
        pass

    def __str__(self):
        return self.name


class Region(OrderedModel):
    destination = models.ForeignKey(
        Destination, on_delete=models.CASCADE, related_name="regions",
    )
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    tagline = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to="regions/", blank=True)

    class Meta(OrderedModel.Meta):
        pass

    def __str__(self):
        return self.name


class Interest(OrderedModel):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True)

    class Meta(OrderedModel.Meta):
        pass

    def __str__(self):
        return self.name


class Trip(models.Model):
    class Difficulty(models.TextChoices):
        EASY = "Easy", _("Easy")
        MODERATE = "Moderate", _("Moderate")
        CHALLENGING = "Challenging", _("Challenging")

    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    summary = models.TextField()
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="trips")
    interests = models.ManyToManyField(Interest, related_name="trips", blank=True)
    duration_days = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    difficulty = models.CharField(max_length=20, choices=Difficulty.choices)
    max_altitude_m = models.PositiveIntegerField()
    group_size = models.CharField(max_length=50)
    best_season = models.CharField(max_length=100)
    price_from_usd = models.DecimalField(max_digits=8, decimal_places=2)
    image = models.ImageField(upload_to="trips/", blank=True)
    is_bestseller = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_bestseller", "title"]

    def __str__(self):
        return self.title


class TripHighlight(OrderedModel):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="highlights")
    text = models.CharField(max_length=255)

    class Meta(OrderedModel.Meta):
        pass

    def __str__(self):
        return self.text


class TripPhoto(OrderedModel):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="trips/gallery/")
    caption = models.CharField(max_length=200, blank=True)

    class Meta(OrderedModel.Meta):
        pass

    def __str__(self):
        return self.caption or f"Photo {self.pk} — {self.trip}"


class ItineraryDay(OrderedModel):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="itinerary")
    day_label = models.CharField(max_length=30, help_text='e.g. "Day 1" or "Days 3–4"')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta(OrderedModel.Meta):
        pass

    def __str__(self):
        return f"{self.day_label}: {self.title}"


class TripInclusion(OrderedModel):
    class Kind(models.TextChoices):
        INCLUDED = "included", _("Included")
        EXCLUDED = "excluded", _("Not included")

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="inclusions")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    text = models.CharField(max_length=255)

    class Meta(OrderedModel.Meta):
        pass

    def __str__(self):
        return self.text


class Departure(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="departures")
    start_date = models.DateField()
    price_usd = models.DecimalField(max_digits=8, decimal_places=2)
    seats_total = models.PositiveSmallIntegerField(default=12)
    seats_booked = models.PositiveSmallIntegerField(default=0)
    is_open = models.BooleanField(
        default=True, help_text="Untick to stop taking bookings for this date.",
    )

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(seats_booked__lte=F("seats_total")),
                name="departure_not_overbooked",
            ),
        ]

    def __str__(self):
        return f"{self.trip.title} — {self.start_date:%d %b %Y}"

    @property
    def seats_left(self):
        return self.seats_total - self.seats_booked


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        CONFIRMED = "confirmed", _("Confirmed")
        CANCELLED = "cancelled", _("Cancelled")

    departure = models.ForeignKey(
        Departure, on_delete=models.PROTECT, related_name="bookings",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
    )
    lead_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    travellers = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    message = models.TextField(blank=True)
    total_usd = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.lead_name} × {self.travellers} — {self.departure}"


class Review(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )
    name = models.CharField(max_length=100)
    country = models.CharField(max_length=100, blank=True)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    title = models.CharField(max_length=150)
    body = models.TextField()
    is_published = models.BooleanField(
        default=False, help_text="Reviews only appear on the site once published.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="review_rating_1_to_5",
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.trip} ({self.rating}★)"
