from celery import shared_task
from .models import Student
from .services import generate_course_recommendations
from django.core.cache import cache
import requests
import logging

logger = logging.getLogger(__name__)

@shared_task(
    bind=True,
    autoretry_for=(requests.exceptions.RequestException,),
    max_retries=3,
    default_retry_delay=60
)
def generate_recommendations_task(self, student_id, college_id, model_provider):
    try:
        student = Student.objects.get(pk=student_id)
        college = student.college 

        cache_key = f"courses_{college.college_id}"
        available_courses = cache.get(cache_key)
        if not available_courses:
            try:
                response = requests.get(f"{college.base_url}/website/ReadCourseDetails")
                response.raise_for_status()
                available_courses = response.json()
                cache.set(cache_key, available_courses, timeout=3600)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to fetch courses for {college.name}. Retrying... Error: {e}")
                raise

        recommendations_data = generate_course_recommendations(
            student, available_courses, model_provider=model_provider
        )

        if 'error' in recommendations_data:
            logger.error(f"Failed to generate recommendations for student {student_id}: {recommendations_data['error']}")
            raise Exception(recommendations_data['error'])

        student.recommendations = {
            "courses": recommendations_data.get("recommendations", []),
            "skillset": recommendations_data.get("skillset", [])
        }
        student.recommendation_status = 'COMPLETED'
        student.recommendation_error = None
        student.save(update_fields=['recommendations', 'recommendation_status', 'recommendation_error'])

        logger.info(f"Successfully generated recommendations for student {student_id}")
        return {"status": "success", "student_id": student_id}

    except Student.DoesNotExist:
        logger.error(f"Student with ID {student_id} not found in background task.")
        return {"error": f"Student {student_id} not found."}
    except Exception as e:
        logger.error(f"An unexpected error occurred for student {student_id}: {e}")
        try:
            if 'student' in locals():
                student.recommendation_status = 'FAILED'
                student.recommendation_error = str(e)
                student.save(update_fields=['recommendation_status', 'recommendation_error'])
        except Exception as save_e:
            logger.error(f"Could not save FAILED status for student {student_id}: {save_e}")
            
        return {"error": str(e)}