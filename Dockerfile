# --- Stage 1: Build Stage ---
# Use a specific Python version for reproducibility.
FROM python:3.11-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory
WORKDIR /app

# Install dependencies
# Copy only requirements.txt first to leverage Docker cache
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt


# --- Stage 2: Final Stage ---
# Use the same base image
FROM python:3.11-slim

# Create a non-root user for security
RUN addgroup --system app && adduser --system --group app

# Set environment variables for the final image
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
# The following variables should be passed at runtime
# ENV SECRET_KEY=...
# ENV DEBUG=False
# ENV ALLOWED_HOSTS=...
# ENV GEMINI_API_KEY=...
# ENV DB_NAME=...
# ENV DB_USER=...
# ENV DB_PASSWORD=...
# ENV DB_HOST=...
# ENV DB_PORT=...

WORKDIR /app

# Copy installed wheels from the builder stage
COPY --from=builder /app/wheels /wheels

# Install dependencies from wheels
RUN pip install --no-cache /wheels/*

# Copy the project source code
COPY . .

# Set ownership of the files to the app user
RUN chown -R app:app /app


# Switch to the non-root user
USER app

# Expose the port Gunicorn will run on
EXPOSE 8000

# Run the Gunicorn server
# This is the command that will start the application
# We use --bind 0.0.0.0 to listen on all network interfaces
CMD ["gunicorn", "college_management.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
