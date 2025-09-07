

# 🎓 College Recommendation System

An asynchronous Django-based student survey system that uses a Celery task queue to generate course recommendations from multiple LLM providers (including **Google Gemini**, **OpenAI**, and **DeepSeek**).

The system validates student answers and schedules a background task, allowing for complex, multi-step API calls to the AI models without timing out the user's web request.

-----

## ⚙️ Technology Stack

  * **Backend:** Django, Django REST Framework
  * **Database:** PostgreSQL
  * **Task Queue:** Celery
  * **Message Broker:** Redis
  * **LLM APIs:** Google Gemini, OpenAI
  * **Containerization:** Docker & Docker Compose
  * **Server:** Gunicorn

-----

## 🚀 Getting Started (Docker - Recommended)

This project is fully containerized. The simplest way to run it locally is with Docker Compose, which will automatically build the image, start the database, and run the three required services:

1.  **web** (Django/Gunicorn server)
2.  **redis** (Celery broker and results backend)
3.  **celery\_worker** (Background worker to process recommendation tasks)

### 1\. Prerequisites

  * Docker
  * Docker Compose

### 2\. Configuration

Clone the repository and create your `.env` file in the project root.

```bash
cp .env.example .env
```

Now, edit your **`.env`** file. It must include the new Celery/Redis variables:

```env
# Django secret key
SECRET_KEY=django-insecure-@=gtp^zk@nk9lp#jzq0z2+5jb4n+5n=$@m@vmp8*d8#kqs6%az

# Google Gemini API Key
GEMINI_API_KEY=your_gemini_api_key_here

# OpenAI API Key (Optional)
OPENAI_API_KEY=your_openai_api_key_here

# DeepSeek API Key (Optional)
DEEPSEEK_API_KEY=your_deepseek_api_key_here

# PostgreSQL DB Configuration (Handled by Docker Compose)
# This uses the 'db' service name from docker-compose.yml
DB_NAME=college_rec_db
DB_USER=ashiq
DB_PASSWORD=supersecretpassword
DB_HOST=db 
DB_PORT=5432

# --- CELERY & REDIS ---
# This points to the 'redis' service in docker-compose.yml
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

### 3\. Build and Run the Application

```bash
# Build the images from the Dockerfile
docker-compose build

# Start all services (web, redis, celery_worker) in the background
docker-compose up -d
```

### 4\. Database Setup (First Time Only)

You only need to do this once.

```bash
# Run database migrations
docker-compose exec web python manage.py migrate

# Create your admin superuser
docker-compose exec web python manage.py createsuperuser
```

Your application is now running\!

  * **API:** `http://localhost:8000/api/`
  * **Admin Panel:** `http://localhost:8000/admin/`

-----

## architecture-flow Async API Flow (Important\!)

Generating AI recommendations is slow (20-40 seconds). To prevent server timeouts, this application is **asynchronous**.

1.  The frontend submits student answers to `/api/submit-answers/`.
2.  The server validates the answers, sets the student's status to `PENDING`, schedules a background task with Celery, and **immediately returns a `202 Accepted`** response. This request is very fast.
3.  The frontend receives this initial "Pending" status and must then begin **Polling** the `/api/student-recommendation/<student_id>/<college_name>/` endpoint (e.g., once every 3-5 seconds).
4.  As long as the `celery_worker` is busy, this polling endpoint will check the database and return a **`202 Accepted`** response body (like `{"status": "PENDING", ...}`). This confirms the job is still running.
5.  **If the worker fails** (due to an API error, etc.), it updates the status to `FAILED`. The next poll will return a **`500 Internal Server Error`** with a `{"status": "FAILED"}` body and error details.
6.  **If the worker succeeds**, it updates the status to `COMPLETED`. The next poll will return a **`200 OK`** with a `{"status": "COMPLETED"}` body and the final JSON recommendation data.
7.  The frontend stops polling as soon as it receives a status of either "COMPLETED" or "FAILED".

-----

## 📡 API Endpoints

All APIs are prefixed with `/api/` and require JWT Bearer Token authentication (except for the token endpoints themselves).

### 1\. `POST /api/register-student/`

Register a new student.

#### Request:

```json
{
  "student_id": "ST001",
  "name": "Alice",
  "department": "CS",
  "semester": "First Semester",
  "college_name": "ABC College"
}
```

-----

### 2\. `GET /api/questions/<college_name>/`

Get all survey questions for a specific college.

-----

### 3\. `POST /api/submit-answers/`

**[ASYNC START]** Submits answers and schedules a background job. Does **not** return recommendations.

#### Request:

```json
{
  "student_id": "ST001",
  "college_name": "ABC College",
  "model": "gemini", 
  "answers": {
    "Q1": "A",
    "Q2": "C"
  }
}
```

#### Response (202 Accepted):

```json
{
  "status": "pending",
  "message": "Your answers have been submitted. Recommendations are being generated and will be available shortly."
}
```

-----

### 4\. `GET /api/student-recommendation/<student_id>/<college_name>/`

**[ASYNC POLLING]** The frontend must poll this endpoint to get the final result. Our new logic provides three distinct states:

  * **While task is processing:** Returns `202 Accepted`
  * **If task fails:** Returns `500 Internal Server Error`
  * **When task is complete:** Returns `200 OK`

#### Response (202 Accepted - While Processing):

```json
{
    "status": "PENDING",
    "message": "Recommendations are still being generated. Please check back later."
}
```

#### Response (500 Internal Server Error - On Failure):

```json
{
    "status": "FAILED",
    "error": "Failed to generate recommendations.",
    "detail": "Failed during recommendation for course group 'Minor Courses Basket 1': Error code: 429..."
}
```

#### Response (200 OK - On Success):

```json
{
    "status": "COMPLETED",
    "recommendations": {
        "courses": [
            {
                "SubjectName": "AI",
                "PaperName": "Machine Learning",
                "SubjectGroupName": "Data"
            }
        ],
        "skillset": ["Problem Solving", "Data Analysis"]
    }
}
```

-----

### 5\. `GET /api/college-recommendations/<college_name>/`

Fetch all saved recommendations for all students in a specific college.

-----

### 6\. `POST /api/token/`

Authenticate a user and get JWT access/refresh tokens.

### 7\. `POST /api/token/refresh/`

Obtain a new access token using a valid refresh token.

-----