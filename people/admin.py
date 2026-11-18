from django.contrib import admin

from .models import OneOnOne, PeopleReview, SuccessStatement, ValueRating


class ValueRatingInline(admin.TabularInline):
    model = ValueRating
    extra = 0


@admin.register(PeopleReview)
class PeopleReviewAdmin(admin.ModelAdmin):
    list_display = ["person", "reviewer", "date"]
    inlines = [ValueRatingInline]


admin.site.register(OneOnOne, list_display=["person", "manager", "date"])
admin.site.register(SuccessStatement, list_display=["person", "text", "sort"])
