from django import forms

from .models import User

INPUT = (
    "block w-full rounded-lg border bg-white px-3 py-2 text-[15px] placeholder:text-neutral-400 "
    "disabled:bg-neutral-50"
)
CHECK = "h-4 w-4 rounded border-neutral-300 text-black accent-black"


class StyledForm:
    """Mixin: Tailwind classes on every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
                w.attrs.setdefault("class", CHECK)
            else:
                w.attrs.setdefault("class", INPUT)
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 3)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(**kwargs)


def people_choices(team=None, include=None):
    """Team members (or everyone when the team has none, or is the Company roll-up), plus any ids in `include`."""
    from django.db.models import Q

    extra = [i for i in (include or []) if i]
    cond = Q(is_active=True)
    if team is not None and not team.is_leadership and team.members.exists():
        cond = Q(teams=team)
    if extra:
        cond |= Q(pk__in=extra)
    return User.objects.filter(cond).distinct().order_by("name")


def owner_choices(team=None, *, user=None, instance=None, extra=()):
    """The one list of people an owner/assignee select offers, for the form field AND the rendered template.

    It always includes the person using the form (they are preselected as the owner, even when they are an
    admin who is not on the team) and the instance's current owner on edit. Build every owner select from
    this, never from `people_choices` directly, so what is rendered is always what the form accepts.
    """
    ids = [getattr(user, "pk", None), getattr(instance, "owner_id", None), *extra]
    return people_choices(team, include=ids)


class PersonField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.display_name
