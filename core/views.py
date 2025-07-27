from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.conf import settings # Import Django settings
from dotenv import load_dotenv
load_dotenv()
from .models import College, Question, Student, Option
from .serializers import (
    QuestionSerializer, StudentSerializer,
    StudentRecommendationSerializer
)

import requests
import logging
from .services import generate_course_recommendations

logger = logging.getLogger(__name__)


# API: Register Student
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
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
@permission_classes([permissions.IsAuthenticated])
def get_college_questions(request, college_name):
    try:
        college = College.objects.get(name=college_name)
    except College.DoesNotExist:
        return Response(
            {'error': f"College with name '{college_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    questions = Question.objects.filter(college=college).prefetch_related('option_set')
    serializer = QuestionSerializer(questions, many=True)
    return Response(serializer.data)


# API: Submit student answers and get course recommendations
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def submit_answers(request):
    # NEW: Check if the recommendation service is configured and available
    if not settings.GEMINI_API_KEY:
        logger.error("Attempted to generate recommendations, but GEMINI_API_KEY is not set.")
        return Response(
            {'error': 'The recommendation service is temporarily unavailable. Please try again later.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
        
    student_id = request.data.get('student_id')
    answers = request.data.get('answers')
    college_name = request.data.get('college_name')

    if not student_id or not answers or not college_name:
        return Response(
            {'error': 'student_id, answers, and college_name are required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        college = College.objects.get(name=college_name)
    except College.DoesNotExist:
        return Response(
            {'error': f"College with name '{college_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
        )
    
    try:
        student = Student.objects.get(student_id=student_id, college=college)
    except Student.DoesNotExist:
        return Response(
            {'error': f"Student with ID '{student_id}' not found in college '{college_name}'."},
            status=status.HTTP_404_NOT_FOUND
        )

    valid_question_ids = set(Question.objects.filter(college=college).values_list('question_id', flat=True))
    submitted_question_ids = set(answers.keys())

    if not submitted_question_ids.issubset(valid_question_ids):
        invalid_ids = submitted_question_ids - valid_question_ids
        return Response(
            {'error': f"The following question IDs do not belong to college '{college_name}': {list(invalid_ids)}"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    valid_options = Option.objects.filter(
        question__college=college, 
        question__question_id__in=submitted_question_ids
    ).values('question__question_id', 'value')
    
    valid_option_set = {(opt['question__question_id'], opt['value']) for opt in valid_options}
    
    invalid_answers = []
    for q_id, ans_val in answers.items():
        if (q_id, ans_val) not in valid_option_set:
            invalid_answers.append({q_id: ans_val})

    if invalid_answers:
        return Response(
            {'error': "Invalid option provided for one or more questions.", 'details': invalid_answers},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    student.responses = answers

    cache_key = f"courses_{college.college_id}"
    available_courses = cache.get(cache_key)
    if not available_courses:
        try:
            response = requests.get(f"{college.base_url}/website/ReadCourseDetails")
            response.raise_for_status()
            available_courses = response.json()
            cache.set(cache_key, available_courses, timeout=3600)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch courses for college '{college.name}': {e}")
            return Response(
                {'error': 'Failed to fetch course list from the college. Please try again later.'},
                status=status.HTTP_502_BAD_GATEWAY
            )

    recommendations_data = generate_course_recommendations(student, available_courses)

    student.recommendations = {
    "courses": recommendations_data.get("recommendations", []),
    "skillset": recommendations_data.get("skillset", [])
    }
    student.save()

    return Response({
        "recommendations": recommendations_data.get("recommendations", []),
        "skillset": recommendations_data.get("skillset", [])
    }, status=status.HTTP_200_OK)


# API: Get stored student recommendations
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_student_recommendation(request, student_id, college_name):
    try:
        college = College.objects.get(name=college_name)
    except College.DoesNotExist:
        return Response(
            {'error': f"College with name '{college_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
        )
    
    try:
        student = Student.objects.get(student_id=student_id, college=college)
    except Student.DoesNotExist:
        return Response(
            {'error': f"Student with ID '{student_id}' not found in college '{college_name}'."},
            status=status.HTTP_404_NOT_FOUND
        )

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
@permission_classes([permissions.IsAuthenticated])
def get_college_recommendations(request, college_name):
    try:
        college = College.objects.get(name=college_name)
    except College.DoesNotExist:
        return Response(
            {'error': f"College with name '{college_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
        )
        
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