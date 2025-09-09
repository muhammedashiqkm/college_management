import google.generativeai as genai
import openai
from django.conf import settings
import json
import logging
from .models import Question, RecommendationSetting
from pydantic import BaseModel, ValidationError
from typing import List, Dict
import asyncio
from asgiref.sync import sync_to_async

# Get an instance of a logger
logger = logging.getLogger(__name__)

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


def initialize_gemini_async():
    """Configures and returns a Gemini generative model instance (client is async-compatible)."""
    try:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        return genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini (async): {e}")
        return None

def initialize_openai_async():
    """Configures and returns an ASYNC OpenAI client instance."""
    try:
        return openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI (async): {e}")
        return None

def initialize_deepseek_async():
    """Configures and returns an ASYNC OpenAI-compatible client for DeepSeek."""
    try:
        return openai.AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_API_BASE
        )
    except Exception as e:
        logger.error(f"Failed to initialize DeepSeek (async): {e}")
        return None


class RecommendationSchema(BaseModel):
    recommendations: List[Dict[str, str]]
    skillset: List[str]



def safe_parse_json(response_text: str):
    """Cleans and parses JSON text returned by LLMs."""
    cleaned = response_text.strip().replace('```json', '').replace('```', '')
    return json.loads(cleaned)


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



async def _generate_for_group(client, model_provider, model_name, prompt_content, schema):
    """Async helper to run generation for one subject group."""
    try:
        parsed_json = None
        if model_provider == "gemini":
            response = await client.generate_content_async(
                prompt_content,
                generation_config={"response_mime_type": "application/json", "response_schema": schema},
            )
            parsed_json = json.loads(response.text)

        else: 
            completion = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that only responds in valid JSON."},
                    {"role": "user", "content": prompt_content}
                ],
                response_format={"type": "json_object"}
            )
            parsed_json = safe_parse_json(completion.choices[0].message.content)

        validated = RecommendationSchema.parse_obj(parsed_json)
        return validated 
        
    except Exception as e:
        logger.error(f"Async generation failed for provider '{model_provider}': {e}")
        return None

async def generate_course_recommendations_async(student, available_courses, model_provider="gemini"):
    """
    Generates course recommendations using the specified LLM provider (ASYNC VERSION).
    Runs all subject group generations in parallel.
    """
    college = student.college
    student_semester = student.semester
    
    enriched_responses = await sync_to_async(map_option_values_to_text)(student)

    client = None
    model_name = None
    if model_provider == "gemini":
        client = initialize_gemini_async()
        model_name = settings.GEMINI_MODEL_NAME
    elif model_provider == "openai":
        client = initialize_openai_async()
        model_name = settings.OPENAI_MODEL_NAME
    elif model_provider == "deepseek":
        client = initialize_deepseek_async()
        model_name = settings.DEEPSEEK_MODEL_NAME

    if not client:
        return {"error": f"Failed to initialize the '{model_provider}' async client."}

    grouped_courses = {}
    for course in available_courses:
        group = course.get('SubjectGroupName', 'Unknown')
        grouped_courses.setdefault(group, []).append(course)

    group_names = grouped_courses.keys()
    
    def _get_settings_sync():
        qs = RecommendationSetting.objects.filter(
            college=college, subject_group_name__in=group_names
        )
        return list(qs)

    settings_list = await sync_to_async(_get_settings_sync)()
    settings_map = {s.subject_group_name: s for s in settings_list}

    generation_tasks = []

    gemini_schema = {
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
            },
            "skillset": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["recommendations", "skillset"]
    }

    for group_name, courses_in_group in grouped_courses.items():
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
You are an expert academic advisor. Your task is to perform two distinct actions based on the provided data.

**Student's Survey Responses:**
{json.dumps(enriched_responses, indent=2)}

**Available {group_name} Courses (for the student's semester):**
{json.dumps(filtered_courses_for_semester, indent=2)}

**Instructions:**
1.  **Course Recommendation**: Analyze the student's preferences from their survey responses and recommend exactly {num_recommend} of the most suitable courses from the "Available {group_name} Courses" list.
2.  **Skillset Identification**: Based ONLY on the "Student's Survey Responses", identify and list the skills the student either possesses or is interested in developing. This skillset should be derived directly from their answers, not from the courses.

**Output Format:**
Return a single, clean JSON object. Respond ONLY with valid JSON.
{{
  "recommendations": [
    {{"SubjectName": "...", "PaperName": "..."}},
    ...
  ],
  "skillset": ["Skill derived from survey A", "Skill derived from survey B", ...]
}}
"""
        
        generation_tasks.append(
            (group_name, _generate_for_group(
                client, model_provider, model_name, prompt_content, gemini_schema
            ))
        )

    if not generation_tasks:
         return {
            "recommendations": [],
            "skillset": []
        }

    task_coroutines = [task for _, task in generation_tasks]
    task_results = await asyncio.gather(*task_coroutines)

    final_recommendations = []
    all_skillsets = set()

    for i, validated_data in enumerate(task_results):
        group_name = generation_tasks[i][0] 
        
        if validated_data:
            try:
                for rec in validated_data.recommendations:
                    rec['SubjectGroupName'] = group_name
                final_recommendations.extend(validated_data.recommendations)
                all_skillsets.update(validated_data.skillset)
            except Exception as e:
                 logger.error(f"Failed to process validated data for group {group_name}: {e}")
        else:
            logger.warning(f"Generation task for group '{group_name}' failed and returned None.")

    return {
        "recommendations": final_recommendations,
        "skillset": list(all_skillsets)
    }