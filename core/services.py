import google.generativeai as genai
from django.conf import settings
import json
import logging
from .models import Question, Option, RecommendationSetting, Student

# Get an instance of a logger
logger = logging.getLogger(__name__)

def initialize_gemini():
    """Configures and returns a Gemini generative model instance."""
    genai.configure(api_key=settings.GEMINI_API_KEY)
    # Use the model name from settings
    return genai.GenerativeModel(settings.GEMINI_MODEL_NAME)

def map_option_values_to_text(student):
    """
    Converts student's selected option values into human-readable text,
    ensuring questions are matched within the student's college.
    """
    enriched = {}
    if not student.responses:
        return enriched

    qids = student.responses.keys()
    questions = Question.objects.filter(
        question_id__in=qids, college=student.college
    ).prefetch_related('option_set')

    question_map = {q.question_id: q for q in questions}

    for qid, selected_value in student.responses.items():
        question = question_map.get(qid)
        if question:
            try:
                option = next(opt for opt in question.option_set.all() if opt.value == selected_value)
                enriched[question.text] = option.text
            except StopIteration:
                logger.warning(
                    f"Data integrity issue: Selected value '{selected_value}' for Question "
                    f"'{question.text}' (ID: {qid}) was not found for college '{student.college.name}'."
                )
                enriched[f"Question ID {qid}"] = f"Selected value '{selected_value}' not found for this option set."
        else:
            logger.warning(
                f"Data integrity issue: Question ID '{qid}' from student response was "
                f"not found for college '{student.college.name}'."
            )
            enriched[f"Question ID {qid}"] = "Question not found for this college."
    return enriched

def generate_course_recommendations(student, available_courses):
    """
    Generates course recommendations using the Gemini model based on student survey responses.
    If the API call fails, it returns a dictionary with an 'error' key.
    """
    college = student.college
    student_semester = student.semester
    enriched_responses = map_option_values_to_text(student)

    grouped_courses = {}
    for course in available_courses:
        group = course.get('SubjectGroupName', 'Unknown')
        grouped_courses.setdefault(group, []).append(course)
        
    group_names = grouped_courses.keys()
    settings_qs = RecommendationSetting.objects.filter(
        college=college, subject_group_name__in=group_names
    )
    settings_map = {s.subject_group_name: s for s in settings_qs}

    final_recommendations = []
    all_skillsets = set()
    model = initialize_gemini()

    for group_name, courses_in_group in grouped_courses.items():
        filtered_courses_for_semester = courses_in_group
        if student_semester:
            filtered_courses_for_semester = [
                c for c in courses_in_group if c.get('SemesterName', '').lower() == student_semester.lower()
            ]

        if not filtered_courses_for_semester:
            continue
        
        setting = settings_map.get(group_name)
        if not setting:
            continue
            
        num_recommend = setting.num_recommendations

        # --- PROMPT MODIFICATION ---
        # The prompt is updated to explicitly separate the logic for course recommendations and skillset identification.
        prompt = f"""
You are an expert academic advisor. Your task is to perform two distinct actions based on the provided data.

**Student's Survey Responses:**
{json.dumps(enriched_responses, indent=2)}

**Available {group_name} Courses (for the student's semester):**
{json.dumps(filtered_courses_for_semester, indent=2)}

**Instructions:**
1.  **Course Recommendation**: Analyze the student's preferences from their survey responses and recommend exactly {num_recommend} of the most suitable courses from the "Available {group_name} Courses" list.
2.  **Skillset Identification**: Based *ONLY* on the "Student's Survey Responses", identify and list the skills the student either possesses or is interested in developing. This skillset should be derived directly from their answers, not from the courses.

**Output Format:**
Return a single, clean JSON object. Do not include any text or markdown formatting before or after the JSON.
{{
  "recommendations": [
    {{"SubjectName": "...", "PaperName": "..."}},
    ...
  ],
  "skillset": ["Skill derived from survey A", "Skill derived from survey B", ...]
}}
"""
        # --- END OF PROMPT MODIFICATION ---

        try:
            response = model.generate_content(prompt)
            if not response.text:
                logger.error(f"Gemini API returned an empty response for group '{group_name}'.")
                return {
                    "error": "The recommendation service returned an empty or invalid response. This may be due to an API key issue or temporary service degradation."
                }
            
            cleaned_response = response.text.strip().replace('```json', '').replace('```', '')
            parsed_json = json.loads(cleaned_response)

            if 'recommendations' in parsed_json:
                for rec in parsed_json['recommendations']:
                    rec['SubjectGroupName'] = group_name
                final_recommendations.extend(parsed_json['recommendations'])

            skillset = parsed_json.get('skillset', [])
            all_skillsets.update(skillset)

        except Exception as e:
            logger.error(f"An error occurred while generating recommendations for group '{group_name}': {e}")
            return {
                "error": "An error occurred while communicating with the recommendation service. This could be due to an invalid API key, expired credentials, or a temporary service outage."
            }

    return {
        "recommendations": final_recommendations,
        "skillset": list(all_skillsets)
    }