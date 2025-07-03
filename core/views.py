from rest_framework import viewsets, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import College, Question, Student, CollegeUser
from .serializers import (
    CollegeSerializer, QuestionSerializer, StudentSerializer,
    CollegeUserSerializer, StudentRecommendationSerializer
)

import requests
from .services import generate_course_recommendations


# API: Register Student
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def register_student(request):
    serializer = StudentSerializer(data=request.data)
    if serializer.is_valid():
        student = serializer.save()
        return Response({
            'message': 'Student registered successfully',
            'student_id': student.student_id
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# API: Get questions for a specific college
@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_college_questions(request, college_name):
    college = get_object_or_404(College, name=college_name)
    questions = Question.objects.filter(college=college)
    serializer = QuestionSerializer(questions, many=True)
    return Response(serializer.data)


# API: Submit student answers and get course recommendations
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def submit_answers(request):
    student_id = request.data.get('student_id')
    answers = request.data.get('answers')
    college_name = request.data.get('college_name')

    if not student_id or not answers or not college_name:
        return Response(
            {'error': 'student_id, answers, and college_name are required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Fetch student and college
    student = get_object_or_404(Student, student_id=student_id, college__name=college_name)
    college = student.college

    # FIX: Validate that the questions submitted belong to the student's college
    valid_question_ids = set(Question.objects.filter(college=college).values_list('question_id', flat=True))
    submitted_question_ids = set(answers.keys())

    if not submitted_question_ids.issubset(valid_question_ids):
        invalid_ids = submitted_question_ids - valid_question_ids
        return Response(
            {'error': f"The following question IDs do not belong to college '{college_name}': {list(invalid_ids)}"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    student.responses = answers

    # Fetch available courses from external college API
    try:
        response = requests.get(f"{student.college.base_url}/website/ReadCourseDetails")
        response.raise_for_status()
        available_courses = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch courses: {e}")
        return Response(
            {'error': 'Failed to fetch course list from the college. Please try again later.'},
            status=status.HTTP_502_BAD_GATEWAY
        )

    # Get recommendations from Gemini (pass the full student object)
    recommendations_data = generate_course_recommendations(student, available_courses)

    # Save final recommendations
    student.recommendations = recommendations_data.get('recommendations', [])
    student.save()

    return Response(recommendations_data, status=status.HTTP_200_OK)


# API: Get stored student recommendations
@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_student_recommendation(request, student_id, college_name):
    student = get_object_or_404(Student, student_id=student_id, college__name=college_name)

    if not student.recommendations:
        return Response(
            {'error': 'No recommendations have been generated for this student yet.'},
            status=status.HTTP_404_NOT_FOUND
        )

    return Response({
        "recommendations": student.recommendations
    })


# API: Get all student recommendations for a college
@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_college_recommendations(request, college_name):
    college = get_object_or_404(College, name=college_name)
    students = Student.objects.filter(college=college, recommendations__isnull=False)
    serializer = StudentRecommendationSerializer(students, many=True)
    return Response({
        "college_name": college_name,
        "recommendations": serializer.data
    })


# HTML View: College user panel (for web)
@login_required
def college_user_panel(request):
    if not hasattr(request.user, 'collegeuser'):
        return render(request, 'unauthorized.html')
    
    students = Student.objects.filter(college=request.user.collegeuser.college)
    return render(request, 'college_user_panel.html', {'students': students})