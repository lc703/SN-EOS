"""Who may edit what.

Admins edit everything. Members edit items they own, plus their own teams' issues and to-dos.
Items with no owner can be edited by members of the item's team.
"""


def is_admin(user):
    return bool(user and user.is_authenticated and user.is_admin)


def is_team_member(user, team):
    if not (user and user.is_authenticated and team):
        return False
    return team.members.filter(pk=user.pk).exists()


def can_edit_owned(user, obj, team=None):
    """Rocks, measurables, milestones: admin, owner, or (unowned) a team member."""
    if is_admin(user):
        return True
    owner_id = getattr(obj, "owner_id", None)
    if owner_id:
        return owner_id == user.pk
    return is_team_member(user, team or getattr(obj, "team", None))


def can_edit_team_item(user, obj):
    """Issues and team to-dos: admin, owner, or any member of the item's team."""
    if is_admin(user):
        return True
    if getattr(obj, "owner_id", None) == user.pk:
        return True
    return is_team_member(user, getattr(obj, "team", None))


def can_edit_todo(user, todo):
    if todo.is_private:
        return todo.owner_id == user.pk or (todo.created_by_id == user.pk)
    return can_edit_team_item(user, todo)


def can_view_todo(user, todo):
    if todo.is_private:
        return todo.owner_id == user.pk or todo.created_by_id == user.pk
    return True


def manages(user, person):
    """True if one of user's seats is the parent of one of person's seats."""
    from vision.models import Seat

    return Seat.objects.filter(person=person, parent__person=user).exists()


def can_view_private_people_notes(user, person):
    """1:1 notes and People Analyzer: the person, their manager, and admins."""
    return is_admin(user) or user.pk == person.pk or manages(user, person)


def can_review_person(user, person):
    return is_admin(user) or manages(user, person)
