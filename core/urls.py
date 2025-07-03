from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('register-student/', views.register_student, name='register-student'),
    path('questions/<str:college_name>/', views.get_college_questions, name='college-questions'),
    path('submit-answers/', views.submit_answers, name='submit-answers'),
    path('student-recommendation/<str:student_id>/<str:college_name>/', views.get_student_recommendation, name='student-recommendation'),
    path('college-recommendations/<str:college_name>/', views.get_college_recommendations, name='college-recommendations'),
]
