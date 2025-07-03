from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import College, Question, Option, Student, CollegeUser, RecommendationSetting

# --- Inlines for Richer Detail Views ---

class QuestionInline(admin.TabularInline):
    """
    Allows you to see and add Questions directly on the College detail page.
    This is useful for quickly viewing all questions associated with a college.
    """
    model = Question
    extra = 1  # Number of extra empty forms to display
    show_change_link = True # Adds a link to the detail page of each question

class OptionInline(admin.TabularInline):
    """
    Allows for the direct creation and editing of Options when viewing a Question.
    """
    model = Option
    extra = 3

class RecommendationSettingInline(admin.TabularInline):
    """
    Lets you manage Recommendation Settings directly from the College detail page.
    This centralizes the configuration for each college.
    """
    model = RecommendationSetting
    extra = 1

class StudentInline(admin.TabularInline):
    """
    Displays a list of students associated with a college on its detail page.
    Provides a quick overview of registered students without leaving the college view.
    """
    model = Student
    extra = 0 # No extra forms needed, just for display
    show_change_link = True
    verbose_name_plural = 'Registered Students'
    # Define which fields to show in the inline view
    fields = ('student_id', 'name', 'department', 'semester')
    readonly_fields = ('student_id', 'name', 'department', 'semester')

    def has_add_permission(self, request, obj=None):
        return False # Disable adding students from the college page

    def has_delete_permission(self, request, obj=None):
        return False # Disable deleting students from the college page


# --- Main ModelAdmin Configurations ---

@admin.register(College)
class CollegeAdmin(admin.ModelAdmin):
    """
    Enhanced admin view for the College model.
    Includes inlines for managing related data in one place.
    """
    list_display = ('name', 'college_id', 'base_url')
    search_fields = ('name', 'college_id')
    inlines = [QuestionInline, StudentInline, RecommendationSettingInline]

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    """
    Enhanced admin view for Questions.
    Includes inlines for managing Options.
    """
    list_display = ('text', 'college', 'question_id')
    list_filter = ('college',)
    search_fields = ('text', 'question_id', 'college__name')
    inlines = [OptionInline]

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    """
    Admin view for Students, optimized for searching and filtering.
    Makes it easy to find specific students.
    """
    list_display = ('student_id', 'name', 'college', 'department', 'semester', 'created_at')
    list_filter = ('college', 'department', 'semester')
    search_fields = ('student_id', 'name', 'college__name')
    readonly_fields = ('created_at', 'responses', 'recommendations')
    # Organizes the detail view into sections
    fieldsets = (
        ('Student Information', {
            'fields': ('student_id', 'name', 'college', 'department', 'semester')
        }),
        ('Survey Data', {
            'fields': ('responses', 'recommendations'),
            'classes': ('collapse',) # Makes this section collapsible
        }),
    )

@admin.register(RecommendationSetting)
class RecommendationSettingAdmin(admin.ModelAdmin):
    """
    Admin view for managing recommendation settings.
    Allows for easy filtering by college.
    """
    list_display = ('college', 'subject_group_name', 'num_recommendations')
    list_filter = ('college',)
    search_fields = ('college__name', 'subject_group_name')


# --- Customizing the User Admin ---

class CollegeUserInline(admin.StackedInline):
    """
    Inline for managing CollegeUser profile from the User page.
    """
    model = CollegeUser
    can_delete = False
    verbose_name_plural = 'College Affiliation'

class UserAdmin(BaseUserAdmin):
    """
    Extends the default User admin to include the CollegeUser profile.
    """
    inlines = (CollegeUserInline,)

# Re-register User admin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# Unregister the basic model registrations if they were registered before
# and re-register them with the enhanced admin classes above.
admin.site.register(CollegeUser)
# Note: College, Question, Student, and RecommendationSetting are registered using the @admin.register decorator.
# The Option model is managed inline, so it does not need to be registered separately.