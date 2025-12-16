from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('register-student/', views.register_student, name='register-student'),
    path('questions/<str:college_name>/', views.get_college_questions, name='get_questions'),
    path('questions/add/<str:college_name>/', views.add_questions, name='add_questions'),
    path('question/update/<int:question_pk>/', views.update_question, name='update_question'),
    path('question/delete/<int:question_pk>/', views.delete_question, name='delete_question'),
    path('submit-answers/', views.submit_answers, name='submit-answers'),
    path('student-recommendation/<str:student_id>/<str:college_name>/', views.get_student_recommendation, name='student-recommendation'),
    path('college-recommendations/<str:college_name>/', views.get_college_recommendations, name='college-recommendations'),
    path('api/settings/<str:college_name>/', views.get_recommendation_settings, name='get_settings'),
    path('api/settings/add/<str:college_name>/', views.add_recommendation_setting, name='add_setting'),
    path('api/settings/update/<int:pk>/', views.update_recommendation_setting, name='update_setting'),
    path('api/settings/delete/<int:pk>/', views.delete_recommendation_setting, name='delete_setting'),
    
]