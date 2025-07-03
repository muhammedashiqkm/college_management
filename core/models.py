from django.db import models
from django.contrib.auth.models import User

class College(models.Model):
    college_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200, unique=True)
    base_url = models.URLField()

    def __str__(self):
        return self.name

class RecommendationSetting(models.Model):
    college = models.ForeignKey(College, on_delete=models.CASCADE)
    subject_group_name = models.CharField(max_length=255)
    num_recommendations = models.PositiveIntegerField(default=3)

    def __str__(self):
        return f"{self.college.name} - {self.subject_group_name} ({self.num_recommendations})"

class Question(models.Model):
    question_id = models.CharField(max_length=50)
    college = models.ForeignKey(College, on_delete=models.CASCADE)
    text = models.TextField()

    class Meta:
        unique_together = ('college', 'question_id')

    def __str__(self):
        return f"{self.college.name} - {self.text[:50]}"

class Option(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    text = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.question.text[:30]} - {self.text}"

class Student(models.Model):
    student_id = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    department = models.CharField(max_length=100)
    semester = models.CharField(max_length=20)
    college = models.ForeignKey(College, on_delete=models.CASCADE)
    responses = models.JSONField(null=True, blank=True)
    recommendations = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('college', 'student_id')

    def __str__(self):
        return f"{self.name} ({self.student_id})"

class CollegeUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    college = models.ForeignKey(College, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.college.name} - {self.user.username}"