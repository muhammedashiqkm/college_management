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
from .services import generate_course_recommendations

load_dotenv()
logger = logging.getLogger(__name__)


# --- Reusable Decorator for College Lookup ---

def get_college_by_name(view_func):
    """
    Decorator to fetch a College object by its name from a URL parameter
    or request body and pass it to the view. Handles Not Found errors.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check for 'college_name' in URL keyword arguments first
        college_name = kwargs.get('college_name')

        # If not in URL, check the request body
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
        
        # Pass the fetched college object to the actual view function
        return view_func(request, college=college, *args, **kwargs)
    return _wrapped_view


# --- API Views ---

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def register_student(request):
    """API: Register a new student."""
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
    """API: Get questions for a specific college."""
    questions = Question.objects.filter(college=college).prefetch_related('option_set')
    serializer = QuestionSerializer(questions, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@get_college_by_name
def submit_answers(request, college, **kwargs):
    """API: Submit student answers and get course recommendations."""
    student_id = request.data.get('student_id')
    answers = request.data.get('answers')

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

    # --- Enhanced Validation for Answer Values ---
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
        # If there are invalid answers, prepare a detailed error response
        invalid_question_ids = [list(q.keys())[0] for q in invalid_answers]
        
        # Fetch the correct options for the questions that were answered incorrectly
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

        # Return the new, more informative JSON response
        return Response({
            'error': "Invalid option provided for one or more questions.",
            'details': {
                'submitted_invalid_answers': invalid_answers,
                'available_valid_options': available_options
            }
        }, status=status.HTTP_400_BAD_REQUEST)
    
    student.responses = answers

    # --- Course fetching and recommendation logic remains the same ---
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

    if 'error' in recommendations_data:
        return Response(
            {'error': 'Could not generate recommendations due to a service error.',
             'service_error_details': recommendations_data['error']},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    student.recommendations = {
        "courses": recommendations_data.get("recommendations", []),
        "skillset": recommendations_data.get("skillset", [])
    }
    student.save()

    return Response({
        "recommendations": recommendations_data.get("recommendations", []),
        "skillset": recommendations_data.get("skillset", [])
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@get_college_by_name
def get_student_recommendation(request, student_id, college, **kwargs):
    """API: Get stored recommendations for a specific student."""
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
    """API: Get all student recommendations for a specific college."""
    students = Student.objects.filter(college=college, recommendations__isnull=False)
    serializer = StudentRecommendationSerializer(students, many=True)
    return Response({
        "college_name": college.name,
        "recommendations": serializer.data
    })


# --- HTML View ---

@login_required
def college_user_panel(request):
    """HTML View: Renders the panel for an authenticated college user."""
    if not hasattr(request.user, 'collegeuser'):
        return render(request, 'unauthorized.html')
    
    students = Student.objects.filter(college=request.user.collegeuser.college)
    return render(request, 'college_user_panel.html', {'students': students})