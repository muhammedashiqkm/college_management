# Use official Python base image
FROM python:3.11-slim-bullseye

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (as root)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Set working directory (still as root)
WORKDIR /app

# Copy and install Python dependencies (still as root)
# This ensures executables like 'celery' are installed to /usr/local/bin,
# which is on the global system PATH.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project files (owned by root for now)
COPY . .

# --- NEW: Create user AND change ownership ---
# Now that all files are installed, create the non-root user
RUN addgroup --system django-user && adduser --system --ingroup django-user django-user

# Change ownership of the entire /app directory to the new user
# This allows the user to run the app, read/write files, etc.
RUN chown -R django-user:django-user /app

# --- NEW: Switch to the non-root user at the VERY END ---
USER django-user

# Expose the port
EXPOSE 8000

# Run the CMD. This will now be executed as 'django-user'
CMD ["gunicorn", "--bind", "0.0.0.0:8000","--workers", "4","college_management.wsgi:application"]