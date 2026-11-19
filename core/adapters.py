from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.shortcuts import render


def email_allowed(email):
    return bool(email) and email.lower().endswith("@" + settings.ALLOWED_EMAIL_DOMAIN)


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        # No username/password signup. Accounts come from Google or the importer.
        return False


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def _email(self, sociallogin):
        email = (sociallogin.user.email or "").lower()
        if not email:
            for addr in sociallogin.email_addresses:
                email = addr.email.lower()
                break
        return email

    def pre_social_login(self, request, sociallogin):
        email = self._email(sociallogin)
        if not email_allowed(email):
            raise ImmediateHttpResponse(
                render(request, "account/not_allowed.html", {"email": email}, status=403)
            )

    def is_open_for_signup(self, request, sociallogin):
        return email_allowed(self._email(sociallogin))

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        user.email = (user.email or "").lower()
        user.username = user.email
        full = " ".join(x for x in [data.get("first_name"), data.get("last_name")] if x)
        if full and not user.name:
            user.name = full
        return user
