from django.contrib import admin

from .models import ConversationScore, OneOnOne, PeopleReview, SuccessStatement, ValueRating


class ValueRatingInline(admin.TabularInline):
    model = ValueRating
    extra = 0


@admin.register(PeopleReview)
class PeopleReviewAdmin(admin.ModelAdmin):
    list_display = ["person", "reviewer", "date"]
    inlines = [ValueRatingInline]


class ConversationScoreInline(admin.TabularInline):
    model = ConversationScore
    extra = 0


@admin.register(OneOnOne)
class OneOnOneAdmin(admin.ModelAdmin):
    list_display = ["person", "manager", "kind", "quarter", "date", "completed_at"]
    list_filter = ["kind", "quarter"]
    inlines = [ConversationScoreInline]
admin.site.register(SuccessStatement, list_display=["person", "text", "sort"])
