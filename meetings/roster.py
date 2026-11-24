"""Who is in the meeting decides what the L10 shows.

`Meeting.attendees` is the roster: the team's members when the meeting starts (plus whoever started it),
editable in Segue. Every L10 section shows only the items whose owner is on it. Items with no owner stay
visible (there is nobody to leave out), and a meeting with an empty roster shows everything. Anything hidden is
counted and one click ("Show all") reveals it; nothing is ever dropped from the data.
"""
from django.db.models import Q


class Roster:
    def __init__(self, meeting, show_all=False):
        self.ids = set(meeting.attendees.values_list("pk", flat=True))
        self.available = bool(self.ids)
        self.show_all = bool(show_all)
        self.hidden = 0

    @property
    def filtering(self):
        return self.available and not self.show_all

    def _in_meeting(self, field):
        return Q(**{f"{field}__in": self.ids}) | Q(**{f"{field}__isnull": True})

    def apply(self, qs, field="owner"):
        """`qs` limited to attendees' items (or everyone's when showing all); counts what the roster hides."""
        if not self.available:
            return qs
        self.hidden += qs.exclude(self._in_meeting(field)).count()
        return qs.filter(self._in_meeting(field)) if self.filtering else qs
