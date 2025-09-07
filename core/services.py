import google.generativeai as genai
import openai
from django.conf import settings
import json
import logging
from .models import Question, RecommendationSetting
from pydantic import BaseModel, ValidationError, Field
from typing import List, Dict, Set

# Get an instance of a logger
logger = logging.getLogger(__name__)


# --- LLM Client Initializers ---

def initialize_gemini():
    """Configures and returns a Gemini generative model instance."""
    try:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        return genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini: {e}")
        return None


def initialize_openai():
    """Configures and returns an OpenAI client instance."""
    try:
        return openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI: {e}")
        return None


def initialize_deepseek():
    """Configures and returns an OpenAI-compatible client for DeepSeek."""
    try:
        return openai.OpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_API_BASE
        )
    except Exception as e:
        logger.error(f"Failed to initialize DeepSeek: {e}")
        return None


# --- JSON Schemas ---

class SkillsetSchema(BaseModel):
    """Pydantic schema for validating the skillset-only API call."""
    skillset: List[str] = Field(default_factory=list)

class CourseRecSchema(BaseModel):
    """Pydantic schema for validating the course-only API calls."""
    recommendations: List[Dict[str, str]] = Field(default_factory=list)


# --- Utility for safe JSON parsing ---

def safe_parse_json(response_text: str):
    """Cleans and parses JSON text returned by LLMs."""
    cleaned = response_text.strip().replace('```json', '').replace('```', '')
    return json.loads(cleaned)


# --- Helper to enrich student responses (Unchanged) ---

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
                option = next(
                    opt for opt in question.option_set.all()
                    if opt.value == selected_value
                )
                enriched[question.text] = option.text
            except StopIteration:
                logger.warning(
                    f"Data integrity issue: Selected value '{selected_value}' "
                    f"for Question '{question.text}' (ID: {qid}) "
                    f"was not found for college '{student.college.name}'."
                )
                enriched[f"Question ID {qid}"] = (
                    f"Selected value '{selected_value}' not found for this option set."
                )
        else:
            logger.warning(
                f"Data integrity issue: Question ID '{qid}' from student response "
                f"was not found for college '{student.college.name}'."
            )
            enriched[f"Question ID {qid}"] = "Question not found for this college."
    return enriched

# --- Skillset Helper (CHANGED) ---

def _generate_skillset_from_answers(enriched_responses, client, model_name, provider) -> Set[str]:
    """
    Performs a single API call to generate and consolidate a skillset.
    NOW: Re-raises any exception to fail the main Celery task.
    """
    prompt_content = f"""
You are a career and skills analyst. Your single task is to analyze the following student survey responses.
Based ONLY on these answers, identify and list the skills the student either possesses or is interested in developing.

**Rules:**
1.  Consolidate similar skills. For example, if you find "Programming" and "Python Programming", only return the more specific skill "Python Programming".
2.  Do not include generic skills unless explicitly mentioned.
3.  Standardize capitalization (e.g., use "Python Programming", not "python programming").

**Student's Survey Responses:**
{json.dumps(enriched_responses, indent=2)}

**Output Format:**
Return a single, clean JSON object. Respond ONLY with valid JSON.
{{
  "skillset": ["Skill A", "Skill B", ...]
}}
"""
    try:
        parsed_json = None
        if provider == "gemini":
            schema = {
                "type": "object",
                "properties": {"skillset": {"type": "array", "items": {"type": "string"}}},
                "required": ["skillset"]
            }
            response = client.generate_content(
                prompt_content,
                generation_config={"response_mime_type": "application/json",
                                   "response_schema": schema},
            )
            parsed_json = json.loads(response.text)
        else:  # OpenAI and DeepSeek
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that only responds in valid JSON."},
                    {"role": "user", "content": prompt_content}
                ],
                response_format={"type": "json_object"}
            )
            parsed_json = safe_parse_json(completion.choices[0].message.content)
        
        validated = SkillsetSchema.parse_obj(parsed_json)
        return {skill.strip() for skill in validated.skillset if skill.strip()}

    except Exception as e:
        logger.error(f"Failed to generate skillset with {provider}: {e}")
        # --- THIS IS THE CHANGE ---
        # Instead of returning set(), we re-raise the exception.
        # This will stop the task and be caught by tasks.py.
        raise Exception(f"Failed to generate skillset: {e}")


# --- Main Service Function (CHANGED) ---

def generate_course_recommendations(student, available_courses, model_provider="gemini"):
    """
    Generates course recommendations.
    NOW: Any single API failure in the loop will raise an exception
    and fail the entire task (per user request).
    """
    college = student.college
    student_semester = student.semester
    enriched_responses = map_option_values_to_text(student)

    # --- Initialize Client ---
    client = None
    model_name = None
    if model_provider == "gemini":
        client = initialize_gemini()
        model_name = settings.GEMINI_MODEL_NAME
    elif model_provider == "openai":
        client = initialize_openai()
        model_name = settings.OPENAI_MODEL_NAME
    elif model_provider == "deepseek":
        client = initialize_deepseek()
        model_name = settings.DEEPSEEK_MODEL_NAME

    if not client:
        # This failure path already raises an error correctly.
        return {"error": f"Failed to initialize the '{model_provider}' client."}

    # --- 1. GENERATE SKILLSET (ONE TIME CALL) ---
    # This function will now RAISE an exception if it fails (per the change above)
    # which will be caught by the main try/except block in tasks.py
    all_skillsets = _generate_skillset_from_answers(
        enriched_responses, client, model_name, model_provider
    )

    # --- 2. GROUP COURSES AND GET RECOMMENDATIONS (THE LOOP) ---
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

    for group_name, courses_in_group in grouped_courses.items():
        # Filter by semester
        filtered_courses_for_semester = courses_in_group
        if student_semester:
            filtered_courses_for_semester = [
                c for c in courses_in_group
                if c.get('SemesterName', '').lower() == student_semester.lower()
            ]

        if not filtered_courses_for_semester:
            continue

        setting = settings_map.get(group_name)
        if not setting:
            continue

        num_recommend = setting.num_recommendations

        prompt_content = f"""
You are an expert academic advisor. Your task is to recommend courses.

**Student's Survey Responses:**
{json.dumps(enriched_responses, indent=2)}

**Available {group_name} Courses (for the student's semester):**
{json.dumps(filtered_courses_for_semester, indent=2)}

**Instructions:**
Analyze the student's preferences and recommend exactly {num_recommend} of the most suitable courses from the "Available {group_name} Courses" list.

**Output Format:**
Return a single, clean JSON object. Respond ONLY with valid JSON.
{{
  "recommendations": [
    {{"SubjectName": "...", "PaperName": "..."}},
    ...
  ]
}}
"""
        try:
            parsed_json = None

            if model_provider == "gemini":
                schema = {
                    "type": "object",
                    "properties": {
                        "recommendations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "SubjectName": {"type": "string"},
                                    "PaperName": {"type": "string"}
                                },
                                "required": ["SubjectName", "PaperName"]
                            }
                        }
                    },
                    "required": ["recommendations"]
                }
                
                response = client.generate_content(
                    prompt_content,
                    generation_config={"response_mime_type": "application/json",
                                       "response_schema": schema},
                )
                parsed_json = json.loads(response.text)

            else:  # OpenAI and DeepSeek
                completion = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that only responds in valid JSON."},
                        {"role": "user", "content": prompt_content}
                    ],
                    response_format={"type": "json_object"}
                )
                parsed_json = safe_parse_json(completion.choices[0].message.content)

            try:
                validated = CourseRecSchema.parse_obj(parsed_json)
            except ValidationError as ve:
                logger.error(f"Invalid JSON structure from {model_provider} for course group '{group_name}': {ve}")
                # A validation error is also a failure, raise it.
                raise Exception(f"Invalid JSON received from LLM for group '{group_name}': {ve}")

            # Collect recommendations
            for rec in validated.recommendations:
                rec['SubjectGroupName'] = group_name
            final_recommendations.extend(validated.recommendations)

        # --- THIS IS THE SECOND CHANGE ---
        except Exception as e:
            logger.error(f"An error occurred with provider '{model_provider}' for course group '{group_name}': {e}")
            # Instead of continuing, re-raise the exception to fail the entire task.
            # This will be caught by the main except block in tasks.py.
            raise Exception(f"Failed during recommendation for course group '{group_name}': {e}")

    # --- 3. RETURN THE COMBINED DATA ---
    # This code will now only be reached if ALL API calls succeed.
    return {
        "recommendations": final_recommendations,
        "skillset": list(all_skillsets) 
    }