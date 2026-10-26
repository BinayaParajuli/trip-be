from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from backend.trips.models import Booking
from backend.trips.models import Departure
from backend.trips.models import Review
from backend.trips.models import Trip
from backend.trips.models import TripPhoto


@pytest.fixture
def seeded(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    call_command("seed_trips")


@pytest.fixture
def client():
    return APIClient()


def test_trip_list_is_public_and_paginated(seeded, client):
    res = client.get("/api/trips/")
    assert res.status_code == 200
    body = res.json()
    assert {
        "count",
        "current_page",
        "page_size",
        "total_pages",
        "results",
    } <= body.keys()
    assert body["count"] == Trip.objects.count()
    assert body["results"][0]["is_bestseller"] is True


@pytest.mark.parametrize(
    ("query", "check"),
    [
        ("region=everest", lambda t: t["region"] == "everest"),
        ("interest=wildlife", lambda t: "wildlife" in t["interests"]),
        ("duration=day", lambda t: t["duration_days"] == 1),
        ("duration=15-plus", lambda t: t["duration_days"] >= 15),
    ],
)
def test_trip_filters(seeded, client, query, check):
    results = client.get(f"/api/trips/?{query}").json()["results"]
    assert results
    assert all(check(t) for t in results)


def test_trip_sort_by_price(seeded, client):
    prices = [
        float(t["price_from_usd"])
        for t in client.get("/api/trips/?sort=price-asc&page_size=100").json()[
            "results"
        ]
    ]
    assert prices == sorted(prices)


def test_trip_detail_includes_nested_content(seeded, client):
    body = client.get("/api/trips/everest-base-camp-trek/").json()
    assert body["region_name"] == "Everest"
    assert (
        body["highlights"]
        and body["itinerary"]
        and body["includes"]
        and body["excludes"]
    )
    assert body["itinerary"][0]["day_label"] == "Day 1"


def test_unpublished_trip_is_hidden(seeded, client):
    Trip.objects.filter(slug="everest-base-camp-trek").update(is_published=False)
    assert client.get("/api/trips/everest-base-camp-trek/").status_code == 404


def test_departures_only_upcoming_and_open(seeded, client):
    trip = Trip.objects.first()
    Departure.objects.create(
        trip=trip, start_date=timezone.localdate() - timedelta(days=1), price_usd=100,
    )
    Departure.objects.create(
        trip=trip,
        start_date=timezone.localdate() + timedelta(days=5),
        price_usd=100,
        is_open=False,
    )
    results = client.get("/api/departures/?page_size=100").json()["results"]
    today = timezone.localdate().isoformat()
    assert all(d["start_date"] >= today for d in results)
    assert (
        len(results)
        == Departure.objects.filter(is_open=True, start_date__gte=today).count()
    )


def _booking_payload(departure, travellers=2):
    return {
        "departure": departure.pk,
        "lead_name": "Test Traveller",
        "email": "traveller@example.com",
        "travellers": travellers,
    }


def test_booking_holds_seats_and_prices_total(seeded, client):
    departure = Departure.objects.filter(seats_booked__lte=8).first()
    before = departure.seats_booked
    res = client.post("/api/bookings/", _booking_payload(departure, 2), format="json")
    assert res.status_code == 201, res.json()
    departure.refresh_from_db()
    assert departure.seats_booked == before + 2
    booking = Booking.objects.get()
    assert booking.status == Booking.Status.PENDING
    assert booking.total_usd == departure.price_usd * 2


def test_booking_rejects_overbooking(seeded, client):
    departure = Departure.objects.first()
    res = client.post(
        "/api/bookings/",
        _booking_payload(departure, departure.seats_left + 1),
        format="json",
    )
    assert res.status_code == 400
    assert not Booking.objects.exists()


def test_booking_rejects_closed_departure(seeded, client):
    departure = Departure.objects.first()
    departure.is_open = False
    departure.save()
    res = client.post("/api/bookings/", _booking_payload(departure, 1), format="json")
    assert res.status_code == 400


def test_reseeding_keeps_booked_seats(seeded, client):
    departure = Departure.objects.first()
    client.post("/api/bookings/", _booking_payload(departure, 1), format="json")
    departure.refresh_from_db()
    booked = departure.seats_booked
    call_command("seed_trips")
    departure.refresh_from_db()
    assert departure.seats_booked == booked
    assert Trip.objects.count() == 14


def _review(trip, *, rating=5, published=True):
    return Review.objects.create(
        trip=trip,
        name="Asha",
        rating=rating,
        title="Wonderful",
        body="Great guides.",
        is_published=published,
    )


def test_review_list_shows_only_published_with_average(seeded, client):
    trip = Trip.objects.first()
    _review(trip, rating=5)
    _review(trip, rating=4)
    _review(trip, rating=1, published=False)
    body = client.get(f"/api/reviews/?trip={trip.slug}").json()
    assert body["count"] == 2
    assert body["average_rating"] == 4.5
    assert body["results"][0]["trip"] == trip.slug


def test_review_list_filters_by_destination(seeded, client):
    trip = Trip.objects.select_related("region__destination").first()
    _review(trip)
    destination = trip.region.destination.slug
    assert client.get(f"/api/reviews/?destination={destination}").json()["count"] == 1
    assert client.get("/api/reviews/?destination=nowhere").json()["count"] == 0


def test_review_list_empty_has_null_average(seeded, client):
    body = client.get("/api/reviews/").json()
    assert body["count"] == 0
    assert body["average_rating"] is None


def test_submitted_review_is_held_for_moderation(seeded, client):
    trip = Trip.objects.first()
    res = client.post(
        "/api/reviews/",
        {
            "trip": trip.slug,
            "name": "Sam",
            "rating": 4,
            "title": "Loved it",
            "body": "Would go again.",
        },
        format="json",
    )
    assert res.status_code == 201
    assert Review.objects.get().is_published is False
    assert client.get("/api/reviews/").json()["count"] == 0


@pytest.mark.parametrize("rating", [0, 6])
def test_review_rating_must_be_1_to_5(seeded, client, rating):
    trip = Trip.objects.first()
    res = client.post(
        "/api/reviews/",
        {"trip": trip.slug, "name": "Sam", "rating": rating, "title": "x", "body": "y"},
        format="json",
    )
    assert res.status_code == 400
    assert [e["attr"] for e in res.json()["errors"]] == ["rating"]


def test_trip_detail_lists_photos_in_order(seeded, client):
    trip = Trip.objects.get(slug="everest-base-camp-trek")
    gif = SimpleUploadedFile("p.gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", "image/gif")
    TripPhoto.objects.create(trip=trip, image=gif, caption="Second", order=2)
    TripPhoto.objects.create(trip=trip, image=gif, caption="First", order=1)
    photos = client.get(f"/api/trips/{trip.slug}/").json()["photos"]
    assert [p["caption"] for p in photos] == ["First", "Second"]
    assert photos[0]["image"].startswith("http")


def test_seed_if_empty_leaves_existing_data_alone(seeded):
    trip = Trip.objects.first()
    Trip.objects.filter(pk=trip.pk).update(title="Edited in admin")
    departures = Departure.objects.count()
    call_command("seed_trips", "--if-empty")
    assert Trip.objects.get(pk=trip.pk).title == "Edited in admin"
    assert Departure.objects.count() == departures
