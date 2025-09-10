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

logger = logging.getLogger(__name__)


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

class CourseRecSchema(BaseModel):
    recommendations: List[Dict[str, str]]

class SkillsetSchema(BaseModel):
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

async def _generate_skillset_async(client, model_provider, model_name, prompt_content):
    """Async helper to run generation for the skillset ONLY."""
    try:
        if model_provider == "gemini":
            gemini_schema = {"type": "object", "properties": {"skillset": {"type": "array", "items": {"type": "string"}}}, "required": ["skillset"]}
            response = await client.generate_content_async(
                prompt_content,
                generation_config={"response_mime_type": "application/json", "response_schema": gemini_schema},
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

        validated = SkillsetSchema.parse_obj(parsed_json)
        return validated.skillset
    except Exception as e:
        logger.error(f"Async skillset generation failed for '{model_provider}': {e}")
        return None

async def _generate_recs_for_group_async(client, model_provider, model_name, prompt_content):
    """Async helper to run generation for course recommendations for ONE group."""
    try:
        if model_provider == "gemini":
            gemini_schema = {"type": "object", "properties": {"recommendations": {"type": "array", "items": {"type": "object", "properties": {"SubjectName": {"type": "string"}, "PaperName": {"type": "string"}}, "required": ["SubjectName", "PaperName"]}}}, "required": ["recommendations"]}
            response = await client.generate_content_async(
                prompt_content,
                generation_config={"response_mime_type": "application/json", "response_schema": gemini_schema},
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

        validated = CourseRecSchema.parse_obj(parsed_json)
        return validated.recommendations
    except Exception as e:
        logger.error(f"Async recommendation generation failed for '{model_provider}': {e}")
        return None


async def generate_course_recommendations_async(student, available_courses, model_provider="gemini"):
    """
    Generates course recommendations and skillset by running separate tasks in parallel.
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
    
    all_tasks = []
    skillset_prompt = f"""
You are an expert academic advisor.
Based ONLY on the student's survey responses provided below, identify and list the skills the student either possesses or is interested in developing.

**Student's Survey Responses:**
{json.dumps(enriched_responses, indent=2)}

**Output Format:**
Return a single, clean JSON object with one key, "skillset".
{{
  "skillset": ["Skill derived from survey A", "Skill derived from survey B", ...]
}}
"""
    skillset_task = _generate_skillset_async(client, model_provider, model_name, skillset_prompt)
    all_tasks.append(skillset_task)

    grouped_courses = {}
    for course in available_courses:
        group = course.get('SubjectGroupName', 'Unknown')
        grouped_courses.setdefault(group, []).append(course)

    group_names = grouped_courses.keys()
    settings_list = await sync_to_async(list)(RecommendationSetting.objects.filter(college=college, subject_group_name__in=group_names))
    settings_map = {s.subject_group_name: s for s in settings_list}
    
    course_task_groups = [] 

    for group_name, courses_in_group in grouped_courses.items():
        filtered_courses = [c for c in courses_in_group if c.get('SemesterName', '').lower() == student_semester.lower()]
        setting = settings_map.get(group_name)
        if not filtered_courses or not setting:
            continue

        num_recommend = setting.num_recommendations
        
        recs_prompt = f"""
You are an expert academic advisor.
Analyze the student's preferences from their survey responses and recommend exactly {num_recommend} of the most suitable courses from the "Available Courses" list below.

**Student's Survey Responses:**
{json.dumps(enriched_responses, indent=2)}

**Available {group_name} Courses:**
{json.dumps(filtered_courses, indent=2)}

**Output Format:**
Return a single, clean JSON object with one key, "recommendations".
{{
  "recommendations": [
    {{"SubjectName": "...", "PaperName": "..."}},
    ...
  ]
}}
"""
        rec_task = _generate_recs_for_group_async(client, model_provider, model_name, recs_prompt)
        all_tasks.append(rec_task)
        course_task_groups.append(group_name)

    task_results = await asyncio.gather(*all_tasks)

    final_skillset = task_results[0] if task_results and task_results[0] is not None else []
    final_recommendations = []

    course_results = task_results[1:]
    for i, rec_list in enumerate(course_results):
        if rec_list:
            group_name = course_task_groups[i]
            for rec in rec_list:
                rec['SubjectGroupName'] = group_name
            final_recommendations.extend(rec_list)
        else:
            group_name = course_task_groups[i]
            logger.warning(f"Recommendation task for group '{group_name}' failed and returned None.")
            
    return {
        "recommendations": final_recommendations,
        "skillset": list(set(final_skillset)) 
    }