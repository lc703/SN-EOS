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

    qs = User.objects.filter(is_active=True)
    if team is not None and not team.is_leadership and team.members.exists():
        cond = Q(teams=team)
        extra = [i for i in (include or []) if i]
        if extra:
            cond |= Q(pk__in=extra)
        qs = User.objects.filter(cond)
    return qs.distinct().order_by("name")


class PersonField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.display_name
