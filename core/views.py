from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from dotenv import load_dotenv
from functools import wraps
import requests
import logging
from .models import College, Question, Student, Option
from .serializers import (
    QuestionSerializer, StudentSerializer,
    StudentRecommendationSerializer
)
from .tasks import generate_recommendations_task

load_dotenv()
logger = logging.getLogger(__name__)


def get_college_by_name(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        college_name = kwargs.get('college_name')
        if not college_name:
            college_name = request.data.get('college_name')

        if not college_name:
            return Response(
                {'error': 'A college_name must be provided in the URL or request body.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            college = College.objects.get(name=college_name)
        except College.DoesNotExist:
            return Response(
                {'error': f"College with name '{college_name}' not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        return view_func(request, college=college, *args, **kwargs)
    return _wrapped_view


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


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@get_college_by_name
def get_college_questions(request, college, **kwargs):
    questions = Question.objects.filter(college=college).prefetch_related('option_set')
    serializer = QuestionSerializer(questions, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@get_college_by_name
def submit_answers(request, college, **kwargs):
    student_id = request.data.get('student_id')
    answers = request.data.get('answers')
    
    model_provider = request.data.get('model', 'gemini').lower()
    ALLOWED_MODELS = ['gemini', 'openai', 'deepseek']

    if model_provider not in ALLOWED_MODELS:
        return Response(
            {'error': f"Invalid model provider. Please choose from: {', '.join(ALLOWED_MODELS)}."},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not all([student_id, answers]):
        return Response(
            {'error': 'student_id and answers are required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        student = Student.objects.get(student_id=student_id, college=college)
    except Student.DoesNotExist:
        return Response(
            {'error': f"Student with ID '{student_id}' not found in college '{college.name}'."},
            status=status.HTTP_404_NOT_FOUND
        )

    valid_question_ids = set(Question.objects.filter(college=college).values_list('question_id', flat=True))
    submitted_question_ids = set(answers.keys())

    if not submitted_question_ids.issubset(valid_question_ids):
        invalid_ids = submitted_question_ids - valid_question_ids
        return Response(
            {'error': f"The following question IDs do not belong to college '{college.name}': {list(invalid_ids)}"},
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
        invalid_question_ids = [list(q.keys())[0] for q in invalid_answers]
        options_for_invalid_qs = Option.objects.filter(
            question__college=college,
            question__question_id__in=invalid_question_ids
        ).values('question__question_id', 'value')

        available_options = {}
        for option in options_for_invalid_qs:
            q_id = option['question__question_id']
            if q_id not in available_options:
                available_options[q_id] = []
            available_options[q_id].append(option['value'])

        return Response({
            'error': "Invalid option provided for one or more questions.",
            'details': {
                'submitted_invalid_answers': invalid_answers,
                'available_valid_options': available_options
            }
        }, status=status.HTTP_400_BAD_REQUEST)
    

    student.responses = answers
    student.recommendation_status = 'PENDING'
    student.recommendation_error = None
    student.save(update_fields=['responses', 'recommendation_status', 'recommendation_error']) 

    generate_recommendations_task.delay(
        student_id=student.id,
        college_id=college.id,
        model_provider=model_provider
    )

    return Response({
        "status": "pending",
        "message": "Your answers have been submitted. Recommendations are being generated and will be available shortly."
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@get_college_by_name
def get_student_recommendation(request, student_id, college, **kwargs):
    """
    API: Get stored recommendations for a specific student.
    This now checks the generation status (Pending, Completed, Failed).
    """
    try:
        student = Student.objects.get(student_id=student_id, college=college)
    except Student.DoesNotExist:
        return Response(
            {'error': f"Student with ID '{student_id}' not found in college '{college.name}'."},
            status=status.HTTP_404_NOT_FOUND
        )

    # --- FIX ---
    # Renamed this variable from 'status' to 'job_status' to avoid
    # conflicting with the imported 'status' module from rest_framework.
    job_status = student.recommendation_status

    if job_status == 'COMPLETED':
        return Response({
            "status": "COMPLETED",
            "recommendations": student.recommendations
        }, status=status.HTTP_200_OK)

    elif job_status == 'PENDING':
        return Response({
            "status": "PENDING",
            "message": "Recommendations are still being generated. Please check back later."
        }, status=status.HTTP_202_ACCEPTED)

    elif job_status == 'FAILED':
        return Response({
            "status": "FAILED",
            "error": "Failed to generate recommendations.",
            "detail": student.recommendation_error
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    else:
        return Response(
            {'error': 'No answers have been submitted for this student yet.'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@get_college_by_name
def get_college_recommendations(request, college, **kwargs):
    students = Student.objects.filter(college=college, recommendations__isnull=False)
    serializer = StudentRecommendationSerializer(students, many=True)
    return Response({
        "college_name": college.name,
        "recommendations": serializer.data
    })


@login_required
def college_user_panel(request):
    if not hasattr(request, 'user') or not hasattr(request.user, 'collegeuser'):
        return render(request, 'unauthorized.html')

    students = Student.objects.filter(college=request.user.collegeuser.college)
    return render(request, 'college_user_panel.html', {'students': students})