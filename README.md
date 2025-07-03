
# 🎓 College Recommendation System

A Django-based student survey system that uses **Google Gemini AI** to recommend courses based on student responses.

---

## 📁 Project Structure

```
college_management/
├── college_management/
│   └── settings.py, urls.py, wsgi.py
├── core/
│   └── models.py, views.py, serializers.py, services.py, urls.py
├── staticfiles/
├── .env
├── manage.py
├── requirements.txt
```

---

## ⚙️ Requirements

Install required packages:

```bash
pip install -r requirements.txt
```

### ✅ `requirements.txt`

```txt
Django>=4.2
djangorestframework
python-decouple
psycopg2-binary
requests
google-generativeai
dj-database-url
```

---

## 📦 .env Configuration

Create a `.env` file in your project root:

```env
# Google Gemini API
GEMINI_API_KEY=your_gemini_api_key_here

# PostgreSQL DB Configuration (Render, Railway, etc.)
DB_NAME=college_rec_db
DB_USER=ashiq
DB_PASSWORD=JE7d7PJuN5tGNPfGa2mhRIx4889Cx3hm
DB_HOST=dpg-d1j4946r433s73fqn1s0-a.oregon-postgres.render.com
DB_PORT=5432
```

> Never commit your `.env` — add it to `.gitignore`.

---

## 📡 API Endpoints

All APIs are prefixed with `/api/`

### 1. `POST /api/register-student/`
Register a student

#### Request:
```json
{
  "student_id": "ST001",
  "name": "Alice",
  "department": "CS",
  "semester": "6",
  "college_name": "ABC College"
}
```

#### Response:
```json
{
  "message": "Student registered successfully",
  "student_id": "ST001"
}
```

---

### 2. `GET /api/questions/<college_name>/`
Get all survey questions of a college

#### Example:
`GET /api/questions/ABC College/`

#### Response:
```json
[
  {
    "question_id": "Q1",
    "text": "What is your favorite subject?",
    "options": [
      { "text": "Math", "value": "A" },
      { "text": "Science", "value": "B" }
    ]
  }
]
```

---

### 3. `POST /api/submit-answers/`
Submit student answers and receive recommendations

#### Request:
```json
{
  "student_id": "ST001",
  "college_name": "ABC College",
  "answers": {
    "Q1": "A",
    "Q2": "C"
  }
}
```

#### Response:
```json
{
  "recommendations": [
    {
      "SubjectName": "AI",
      "PaperName": "Machine Learning",
      "SubjectGroupName": "Data"
    }
  ]
}
```

---

### 4. `GET /api/student-recommendation/<student_id>/<college_name>/`
Get saved recommendations for a student

---

### 5. `GET /api/college-recommendations/<college_name>/`
Fetch all recommendations in a college

---

## 🔐 HTML Routes

| Route | Description |
|-------|-------------|
| `/login/` | Django login page |
| `/logout/` | Logout |
| `/panel/` | College user panel (HTML table) |
| `/admin/` | Django admin panel |

---

## 🚀 Deployment (Using WSGI)

### ✅ `wsgi.py` (Already Present)
```python
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'college_management.settings')
application = get_wsgi_application()
```

---

### 🔧 Deployment Options

#### Option A: Using Gunicorn + Nginx
Install Gunicorn:
```bash
pip install gunicorn
```

Run Gunicorn:
```bash
gunicorn college_management.wsgi:application --bind 0.0.0.0:8000
```

Set up Nginx as reverse proxy (optional).

---

#### Option B: Using Render or Railway (Recommended)

1. Create a new Web Service
2. Connect GitHub repo
3. Add environment variables in their UI:
   - `GEMINI_API_KEY`
   - `DB_NAME`, etc.
4. Use build command:
   ```bash
   pip install -r requirements.txt
   ```
5. Use start command:
   ```bash
   gunicorn college_management.wsgi:application
   ```

---

### 💡 Production Tips
- college_management\settings.py -->
- Use `DEBUG = False` in production
- Set `ALLOWED_HOSTS` correctly `ALLOWED_HOSTS = ['']`
- Use PostgreSQL — SQLite is not recommended for production

---

## 👨‍💻 Superuser & Admin Panel

```bash
python manage.py createsuperuser
```

Visit: `http://localhost:8000/admin`



