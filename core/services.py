import google.generativeai as genai
from django.conf import settings
import json
from .models import Question, Option, RecommendationSetting, Student

def initialize_gemini():
    """Configures and returns a Gemini generative model instance."""
    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai.GenerativeModel('models/gemini-1.5-flash')

def map_option_values_to_text(student):
    """
    Converts student's selected option values into human-readable text,
    ensuring questions are matched within the student's college.
    
    Args:
        student (Student): The student instance, containing responses and college info.

    Returns:
        dict: A dictionary with question text as keys and the corresponding selected option text as values.
    """
    enriched = {}
    if not student.responses:
        return enriched

    for qid, selected_value in student.responses.items():
        try:
            # FIX: Look up the question using both its ID and the student's college
            # to prevent mismatching questions from different colleges.
            question = Question.objects.get(question_id=qid, college=student.college)
            option = question.option_set.get(value=selected_value)
            enriched[question.text] = option.text
        except (Question.DoesNotExist, Option.DoesNotExist):
            enriched[f"Question ID {qid} for college {student.college.name}"] = f"Selected: {selected_value} (question or option not found)"
    return enriched

def generate_course_recommendations(student, available_courses):
    """
    Generates course recommendations using the Gemini model based on student survey responses.
    
    Args:
        student (Student): The student instance for whom recommendations are being generated.
        available_courses (list): A list of all available courses from the college.

    Returns:
        dict: A dictionary containing a list of final course recommendations.
    """
    college = student.college
    student_semester = student.semester

    # FIX: Pass the entire student object to the mapping function.
    enriched_responses = map_option_values_to_text(student)

    # First, group all available courses by SubjectGroupName
    grouped_courses = {}
    for course in available_courses:
        group = course.get('SubjectGroupName', 'Unknown')
        grouped_courses.setdefault(group, []).append(course)

    final_recommendations = []

    # Process each subject group separately
    for group_name, courses_in_group in grouped_courses.items():
        
        # Then, filter the courses within that group by SemesterName
        filtered_courses_for_semester = courses_in_group
        if student_semester:
            filtered_courses_for_semester = [
                c for c in courses_in_group if c.get('SemesterName', '').lower() == student_semester.lower()
            ]

        if not filtered_courses_for_semester:
            continue

        try:
            setting = RecommendationSetting.objects.get(college=college, subject_group_name=group_name)
            num_recommend = setting.num_recommendations
        except RecommendationSetting.DoesNotExist:
            continue

        prompt = f"""
You are an expert academic advisor. Based on the student's survey responses and the list of available courses for the "{group_name}" subject group, recommend exactly {num_recommend} of the most suitable courses.

**Student Responses:**
{json.dumps(enriched_responses, indent=2)}

**Available {group_name} Courses (for the student's semester):**
{json.dumps(filtered_courses_for_semester, indent=2)}

**Instructions:**
- Analyze the student's preferences.
- Compare them against the available courses.
- Return exactly {num_recommend} course recommendations from the provided list.
- Your response must be only a JSON object in the following format:
{{
  "recommendations": [
    {{"SubjectName": "...", "PaperName": "..."}},
    ...
  ]
}}
"""
        try:
            model = initialize_gemini()
            response = model.generate_content(prompt)
            cleaned_response = response.text.strip().replace('```json', '').replace('```', '')
            parsed_json = json.loads(cleaned_response)
            
            if 'recommendations' in parsed_json:
                for rec in parsed_json['recommendations']:
                    rec['SubjectGroupName'] = group_name
                final_recommendations.extend(parsed_json['recommendations'])

        except Exception as e:
            print(f"An error occurred while generating recommendations for group '{group_name}': {e}")
            continue

    return {"recommendations": final_recommendations}