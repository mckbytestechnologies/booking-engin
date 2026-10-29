from django.contrib.auth.views import LogoutView
from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from . import views

urlpatterns = [
    path("login/", views.ThrottledLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),          # POST only
    path("register/", views.RegisterView.as_view(), name="register"),
    path("register/verify/", views.RegisterVerifyView.as_view(), name="register_verify"),
    path("", views.AccountView.as_view(), name="account"),
    path("bookings/<str:reference>/cancel/", views.CancelBookingView.as_view(), name="cancel_booking"),
    path("bookings/<str:reference>/extend/", views.ExtendBookingView.as_view(), name="extend_booking"),

    path("password-reset/", views.ThrottledPasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/reset_done.html"), name="password_reset_done"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/reset_complete.html"), name="password_reset_complete"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="accounts/reset_confirm.html",
        success_url=reverse_lazy("password_reset_complete")), name="password_reset_confirm"),
        
]