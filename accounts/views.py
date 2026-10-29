from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.views.generic import FormView, TemplateView

from bookings.models import Booking
from bookings.services.errors import BookingError
from bookings.services.otp import send_otp, verify_otp

from . import throttle
from .forms import CodeForm, EmailLoginForm, RegisterForm
from .services import link_guest_bookings
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from bookings.services.cancellation import assess
from bookings.services.lifecycle import cancel_booking

from bookings.services.stay import request_extension
from .forms import CodeForm, EmailLoginForm, ExtensionForm, RegisterForm

from django.contrib.auth.views import PasswordResetView
from django.urls import reverse_lazy

User = get_user_model()
BACKEND = "accounts.backends.EmailBackend"
PENDING = "pending_registration"


class ThrottledLoginView(LoginView):
    form_class = EmailLoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        self.login_email = request.POST.get("username", "").strip().lower()
        if throttle.is_locked(request, self.login_email):
            # Locked out: do not even evaluate the password.
            ctx = self.get_context_data(form=self.form_class(request=request), locked=True)
            return self.render_to_response(ctx, status=429)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        throttle.clear(self.request, self.login_email)
        return super().form_valid(form)

    def form_invalid(self, form):
        throttle.record_failure(self.request, self.login_email)
        return super().form_invalid(form)


class RegisterView(FormView):
    """Step 1: collect details, email a code. No account exists yet."""
    template_name = "accounts/register.html"
    form_class = RegisterForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("account")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        d = form.cleaned_data
        if throttle.hit("register", self.request, limit=10, window=3600):
            form.add_error(None, "Too many registration attempts. Please try again later.")
            return self.form_invalid(form)
        try:
            send_otp(d["email"])
        except BookingError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        self.request.session[PENDING] = {
            "email": d["email"], "first_name": d["first_name"], "last_name": d["last_name"],
            "password": make_password(d["password1"]),        # hash only
        }
        return redirect("register_verify")


class RegisterVerifyView(FormView):
    """Step 2: the code proves the email is theirs; only now is the account created."""
    template_name = "accounts/register_verify.html"
    form_class = CodeForm

    def dispatch(self, request, *args, **kwargs):
        if PENDING not in request.session:
            return redirect("register")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["email"] = self.request.session[PENDING]["email"]
        return ctx

    def form_valid(self, form):
        pending = self.request.session[PENDING]
        try:
            verify_otp(pending["email"], form.cleaned_data["code"])
        except BookingError as exc:
            form.add_error("code", exc.message)
            return self.form_invalid(form)
        try:
            with transaction.atomic():
                user = User.objects.create(
                    username=pending["email"], email=pending["email"],
                    first_name=pending["first_name"], last_name=pending["last_name"],
                    password=pending["password"],
                )
        except IntegrityError:                         # someone registered it a moment ago
            del self.request.session[PENDING]
            messages.error(self.request, "That email is already registered. Please log in.")
            return redirect("login")
        link_guest_bookings(user)
        del self.request.session[PENDING]
        login(self.request, user, backend=BACKEND)
        return redirect("account")


class AccountView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/account.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["bookings"] = Booking.objects.filter(customer=self.request.user) \
            .select_related("property", "room")
        return ctx

class CancelBookingView(LoginRequiredMixin, View):
    """GET shows what cancelling would cost. Only POST changes anything."""
    template_name = "accounts/cancel.html"

    def _booking(self, request, reference):
        return get_object_or_404(Booking.objects.select_related("property", "room"),
                                 reference=reference, customer=request.user)   # not yours: 404

    def get(self, request, reference):
        booking = self._booking(request, reference)
        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            messages.error(request, "This booking can no longer be cancelled.")
            return redirect("account")
        return render(request, self.template_name, {"booking": booking, "outcome": assess(booking)})

    def post(self, request, reference):
        booking = self._booking(request, reference)
        try:
            outcome = cancel_booking(booking.pk, actor=request.user, reason="Cancelled by guest")
        except BookingError as exc:
            messages.error(request, exc.message)
            return redirect("account")
        text = "Your booking has been cancelled."
        if outcome.refund > 0:
            text += f" A refund of ₹{outcome.refund} will be processed by our team."
        messages.success(request, text)
        return redirect("account")

class ExtendBookingView(LoginRequiredMixin, View):
    """The guest asks. Nothing changes until staff approve."""
    template_name = "accounts/extend.html"

    def _booking(self, request, reference):
        return get_object_or_404(Booking.objects.select_related("property", "room"),
                                 reference=reference, customer=request.user)   # not yours: 404

    def get(self, request, reference):
        booking = self._booking(request, reference)
        if booking.status not in (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN):
            messages.error(request, "This booking can no longer be extended.")
            return redirect("account")
        return render(request, self.template_name, {"booking": booking, "form": ExtensionForm()})

    def post(self, request, reference):
        booking = self._booking(request, reference)
        form = ExtensionForm(request.POST)
        if form.is_valid():
            try:
                request_extension(booking.pk, actor=request.user,
                                  new_check_out=form.cleaned_data["new_check_out"])
            except BookingError as exc:
                form.add_error("new_check_out", exc.message)
            else:
                messages.success(request, "Your extension request was sent. The hotel will confirm it.")
                return redirect("account")
        return render(request, self.template_name, {"booking": booking, "form": form})

class ThrottledPasswordResetView(PasswordResetView):
    template_name = "accounts/reset_form.html"
    email_template_name = "accounts/reset_email.txt"
    subject_template_name = "accounts/reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        if throttle.hit("pwreset", self.request, limit=5, window=3600):
            return redirect(self.success_url)      # same page as success: no signal to an attacker
        return super().form_valid(form)
