from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from dotenv import load_dotenv
from functools import wraps
import httpx     
from asgiref.sync import  sync_to_async
import logging
import asyncio
import json 
from django.http import JsonResponse 
from django.views.decorators.csrf import csrf_exempt 
from rest_framework_simplejwt.authentication import JWTAuthentication 
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError 

from .models import College, Question, Student, Option
from .serializers import (
    QuestionSerializer, StudentSerializer,
    StudentRecommendationSerializer
)
from .services import generate_course_recommendations_async

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
    """API: Register a new student. (Sync DRF view)"""
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
    """API: Get questions for a specific college. (Sync DRF view)"""
    questions = Question.objects.filter(college=college).prefetch_related('option_set')
    serializer = QuestionSerializer(questions, many=True)
    return Response(serializer.data)


async def _run_async_submission(request_data, college):
    student_id = request_data.get('student_id')
    answers = request_data.get('answers')
    model_provider = request_data.get('model', 'gemini').lower()
    ALLOWED_MODELS = ['gemini', 'openai', 'deepseek']

    if model_provider not in ALLOWED_MODELS:
        raise ValueError(f"Invalid model provider. Please choose from: {', '.join(ALLOWED_MODELS)}.")

    if not all([student_id, answers]):
        raise ValueError("student_id and answers are required.")

    try:
        student_getter = Student.objects.select_related('college').get
        student = await sync_to_async(student_getter)(student_id=student_id, college=college)
        
    except Student.DoesNotExist:
        raise Student.DoesNotExist(f"Student with ID '{student_id}' not found in college '{college.name}'.")

    valid_question_ids_qs = Question.objects.filter(college=college).values_list('question_id', flat=True)
    valid_question_ids = set(await sync_to_async(list)(valid_question_ids_qs))
    submitted_question_ids = set(answers.keys())
    if not submitted_question_ids.issubset(valid_question_ids):
        invalid_ids = submitted_question_ids - valid_question_ids
        raise ValueError(f"The following question IDs do not belong to college '{college.name}': {list(invalid_ids)}")
    valid_options_qs = Option.objects.filter(question__college=college, question__question_id__in=submitted_question_ids).values('question__question_id', 'value')
    valid_option_set = await sync_to_async(lambda: {(opt['question__question_id'], opt['value']) for opt in valid_options_qs})()
    for q_id, ans_val in answers.items():
        if (q_id, ans_val) not in valid_option_set:
            raise ValueError(f"Invalid option provided for question {q_id}: {ans_val}")

    student.responses = answers
    cache_key = f"courses_{college.college_id}"
    available_courses = await sync_to_async(cache.get)(cache_key)
    
    if not available_courses:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{college.base_url}/website/ReadCourseDetails")
            response.raise_for_status() 
            available_courses = response.json()
        await sync_to_async(cache.set)(cache_key, available_courses, timeout=3600)

    recommendations_data = await generate_course_recommendations_async(
        student, available_courses, model_provider=model_provider
    )

    if 'error' in recommendations_data:
        raise Exception(f"Service Error: {recommendations_data['error']}")

    courses_data = recommendations_data.get("recommendations", [])
    skillset_data = recommendations_data.get("skillset", [])

    student.recommendations = {
        "courses": courses_data,
        "skillset": list(skillset_data) 
    }
    await sync_to_async(student.save)()

    return {
        "recommendations": courses_data,
        "skillset": list(skillset_data)
    }




@csrf_exempt
async def submit_answers(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method is allowed.'}, status=405)

    auth = JWTAuthentication()
    try:
        user_auth_tuple = await sync_to_async(auth.authenticate)(request)
        if not user_auth_tuple:
            return JsonResponse({'error': 'Authentication credentials were not provided.'}, status=401)
        request.user = user_auth_tuple[0]
    except (InvalidToken, TokenError) as e:
        return JsonResponse({'error': f'Invalid token: {str(e)}'}, status=401)
    except Exception as e:
        return JsonResponse({'error': f'Authentication Failed: {str(e)}'}, status=401)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    college_name = data.get('college_name')
    if not college_name:
        return JsonResponse({'error': 'A college_name must be provided in the request body.'}, status=400)
    try:
        college = await sync_to_async(College.objects.get)(name=college_name)
    except College.DoesNotExist:
        return JsonResponse({'error': f"College with name '{college_name}' not found."}, status=404)

    try:
        result_data = await _run_async_submission(data, college)
        return JsonResponse(result_data, status=200)
    
    except Student.DoesNotExist as e:
        return JsonResponse({'error': str(e)}, status=404)
    except ValueError as e: 
        return JsonResponse({'error': str(e)}, status=400)
    except httpx.RequestError as e:
        logger.error(f"Failed to fetch courses for college '{college.name}': {e}")
        return JsonResponse({'error': 'Failed to fetch course list from the college.'}, status=502)
    except Exception as e:
        logger.error(f"An unhandled error occurred in async submission: {e}")
        return JsonResponse({'error': 'Service unavailable.', 'details': str(e)}, status=503)



@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@get_college_by_name 
def get_student_recommendation(request, student_id, college, **kwargs):
    try:
        student = Student.objects.get(student_id=student_id, college=college)
    except Student.DoesNotExist:
        return Response(
            {'error': f"Student with ID '{student_id}' not found in college '{college.name}'."},
            status=status.HTTP_404_NOT_FOUND
        )
    if not student.recommendations:
        return Response(
            {'error': 'No recommendations have been generated for this student yet.'},
            status=status.HTTP_404_NOT_FOUND
        )
    return Response({"recommendations": student.recommendations})


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


# --- HTML View (Unchanged) ---

@login_required
def college_user_panel(request):
    if not hasattr(request.user, 'collegeuser'):
        return render(request, 'unauthorized.html')
    students = Student.objects.filter(college=request.user.collegeuser.college)
    return render(request, 'college_user_panel.html', {'students': students})