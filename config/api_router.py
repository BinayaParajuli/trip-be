from django.urls import path
from django.conf import settings
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from backend.trips.api.views import BookingViewSet
from backend.trips.api.views import DepartureViewSet
from backend.trips.api.views import DestinationViewSet
from backend.trips.api.views import InterestViewSet
from backend.trips.api.views import RegionViewSet
from backend.trips.api.views import ReviewViewSet
from backend.trips.api.views import TripViewSet
from backend.users.api.views import UserViewSet, UserRegisterationView, UserLoginTokenView

router = DefaultRouter() if settings.DEBUG else SimpleRouter()

router.register("users", UserViewSet)
router.register("destinations", DestinationViewSet, basename="destination")
router.register("regions", RegionViewSet, basename="region")
router.register("interests", InterestViewSet, basename="interest")
router.register("trips", TripViewSet, basename="trip")
router.register("departures", DepartureViewSet, basename="departure")
router.register("bookings", BookingViewSet, basename="booking")
router.register("reviews", ReviewViewSet, basename="review")


app_name = "api"

urlpatterns = [
    path("register/", UserRegisterationView.as_view(), name="register"),
    path("login/", UserLoginTokenView.as_view(), name="login"),

]
urlpatterns += router.urls
