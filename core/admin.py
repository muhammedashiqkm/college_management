from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import College, Question, Option, Student, CollegeUser, RecommendationSetting


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1
    show_change_link = True


class OptionInline(admin.TabularInline):
    model = Option
    extra = 3


class RecommendationSettingInline(admin.TabularInline):
    model = RecommendationSetting
    extra = 1


class StudentInline(admin.TabularInline):
    model = Student
    extra = 0
    show_change_link = True
    verbose_name_plural = "Registered Students"
    fields = ("student_id", "name", "department", "semester")
    readonly_fields = ("student_id", "name", "department", "semester")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(College)
class CollegeAdmin(admin.ModelAdmin):
    list_display = ("name", "college_id", "base_url")
    search_fields = ("name", "college_id")
    inlines = [QuestionInline, StudentInline, RecommendationSettingInline]
    ordering = ("name",)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "college")
    list_filter = ("college",)
    search_fields = ("text", "college__name")
    inlines = [OptionInline]
    ordering = ("college",)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("student_id", "name", "college", "semester", "created_at")
    list_display_links = ("student_id", "name")
    list_filter = ("college", "department", "semester")
    search_fields = ("student_id", "name", "college__name")
    readonly_fields = ("created_at", "recommendations")
    ordering = ("-created_at",)
    autocomplete_fields = ("college",)
    fieldsets = (
        ("Student Information", {
            "fields": ("student_id", "name", "college", "department", "semester"),
        }),
        ("Survey Data", {
            "fields": (
                "responses", 
                "recommendations"   
            ),
            "classes": ("collapse",),
        }),
    )

@admin.register(RecommendationSetting)
class RecommendationSettingAdmin(admin.ModelAdmin):
    list_display = ("college", "subject_group_name", "num_recommendations")
    list_filter = ("college",)
    search_fields = ("college__name", "subject_group_name")
    ordering = ("college", "subject_group_name")


class CollegeUserInline(admin.StackedInline):
    model = CollegeUser
    can_delete = False
    verbose_name_plural = "College Affiliation"


class UserAdmin(BaseUserAdmin):
    inlines = (CollegeUserInline,)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.register(CollegeUser)