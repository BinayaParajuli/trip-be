import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from backend.trips.models import Booking
from backend.trips.models import Departure
from backend.trips.models import Destination
from backend.trips.models import Interest
from backend.trips.models import ItineraryDay
from backend.trips.models import Region
from backend.trips.models import Trip
from backend.trips.models import TripHighlight
from backend.trips.models import TripInclusion

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

# Departure dates in seed.json were written relative to this day; they are
# shifted so the calendar always starts in the near future.
SEED_ANCHOR = date(2026, 10, 26)


class Command(BaseCommand):
    help = "Seed destinations, regions, interests, trips and departures from fixtures/seed.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all trips, departures and bookings first (destructive).",
        )
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="Only seed when there are no trips yet (safe to run on every deploy).",
        )

    def handle(self, *args, reset=False, if_empty=False, **options):
        if if_empty and not reset and Trip.objects.exists():
            self.stdout.write("Trips already exist; skipping seed.")
            return
        data = json.loads((FIXTURES / "seed.json").read_text())
        with transaction.atomic():
            if reset:
                Booking.objects.all().delete()
                Departure.objects.all().delete()
                Trip.objects.all().delete()
                Region.objects.all().delete()
                Destination.objects.all().delete()
                Interest.objects.all().delete()
                self.stdout.write(self.style.WARNING("Existing trip data deleted."))

            interests = self._seed_interests(data["interests"])
            regions = self._seed_destinations(data["destinations"])
            trips = self._seed_trips(data["trips"], regions, interests)
            departures = self._seed_departures(data["departures"], trips)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(interests)} interests, {len(regions)} regions, "
                f"{len(trips)} trips, {departures} departures.",
            ),
        )

    def _attach_image(self, obj, field, public_path):
        """Copy a fixture image onto an ImageField unless one is already set."""
        image_field = getattr(obj, field)
        if image_field or not public_path:
            return
        source = FIXTURES / "images" / Path(public_path).name
        if not source.exists():
            self.stdout.write(
                self.style.WARNING(f"Missing fixture image: {source.name}"),
            )
            return
        with source.open("rb") as fh:
            image_field.save(source.name, File(fh), save=True)

    def _seed_interests(self, items):
        result = {}
        for order, item in enumerate(items):
            interest, _ = Interest.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "order": order,
                },
            )
            result[interest.slug] = interest
        return result

    def _seed_destinations(self, items):
        regions = {}
        for order, item in enumerate(items):
            destination, _ = Destination.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "name": item["name"],
                    "tagline": item["tagline"],
                    "intro": item["intro"],
                    "order": order,
                },
            )
            self._attach_image(destination, "image", item.get("image"))
            for region_order, r in enumerate(item["regions"]):
                region, _ = Region.objects.update_or_create(
                    slug=r["slug"],
                    defaults={
                        "destination": destination,
                        "name": r["name"],
                        "tagline": r.get("tagline", ""),
                        "order": region_order,
                    },
                )
                self._attach_image(region, "image", r.get("image"))
                regions[region.slug] = region
        return regions

    def _seed_trips(self, items, regions, interests):
        trips = {}
        for item in items:
            trip, _ = Trip.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "title": item["title"],
                    "summary": item["summary"],
                    "region": regions[item["region"]],
                    "duration_days": item["durationDays"],
                    "difficulty": item["difficulty"],
                    "max_altitude_m": item["maxAltitudeM"],
                    "group_size": item["groupSize"],
                    "best_season": item["bestSeason"],
                    "price_from_usd": Decimal(item["priceFromUsd"]),
                    "is_bestseller": item.get("bestseller", False),
                    "is_published": True,
                },
            )
            self._attach_image(trip, "image", item.get("image"))
            trip.interests.set([interests[s] for s in item["interests"]])

            # Child rows are owned by the seed: replace them wholesale.
            trip.highlights.all().delete()
            TripHighlight.objects.bulk_create(
                TripHighlight(trip=trip, text=text, order=i)
                for i, text in enumerate(item["highlights"])
            )
            trip.itinerary.all().delete()
            ItineraryDay.objects.bulk_create(
                ItineraryDay(
                    trip=trip,
                    day_label=d["day"],
                    title=d["title"],
                    description=d["description"],
                    order=i,
                )
                for i, d in enumerate(item["itinerary"])
            )
            trip.inclusions.all().delete()
            TripInclusion.objects.bulk_create(
                [
                    *(
                        TripInclusion(
                            trip=trip, kind=TripInclusion.Kind.INCLUDED, text=t, order=i,
                        )
                        for i, t in enumerate(item["includes"])
                    ),
                    *(
                        TripInclusion(
                            trip=trip, kind=TripInclusion.Kind.EXCLUDED, text=t, order=i,
                        )
                        for i, t in enumerate(item["excludes"])
                    ),
                ],
            )
            trips[trip.slug] = trip
        return trips

    def _seed_departures(self, items, trips):
        shift = max(timezone.localdate() - SEED_ANCHOR, SEED_ANCHOR - SEED_ANCHOR)
        count = 0
        for item in items:
            trip = trips[item["tripSlug"]]
            start = date.fromisoformat(item["startDate"]) + shift
            seats_total = 12
            # Seat counts are only set on create, so re-seeding never wipes out real bookings.
            Departure.objects.update_or_create(
                trip=trip,
                start_date=start,
                defaults={"price_usd": Decimal(item["priceUsd"])},
                create_defaults={
                    "price_usd": Decimal(item["priceUsd"]),
                    "seats_total": seats_total,
                    "seats_booked": seats_total - item["seatsLeft"],
                    "is_open": True,
                },
            )
            count += 1
        return count
