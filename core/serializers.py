from rest_framework import serializers
from django.contrib.auth.models import User
from .models import College, Question, Option, Student, CollegeUser,  RecommendationSetting

class CollegeSerializer(serializers.ModelSerializer):
    class Meta:
        model = College
        fields = ['college_id', 'name', 'base_url']

class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ['id','text', 'value']

class QuestionSerializer(serializers.ModelSerializer):
    question_id = serializers.IntegerField(source='id', read_only=True)
    options = OptionSerializer(many=True, read_only=True, source='option_set')
    
    class Meta:
        model = Question
        fields = ['question_id', 'text', 'options']

class RecommendationSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecommendationSetting
        fields = ['id', 'subject_group_name', 'num_recommendations']

class StudentSerializer(serializers.ModelSerializer):
    college_name = serializers.CharField(write_only=True)

    class Meta:
        model = Student
        fields = ['student_id', 'name', 'department', 'semester', 'college', 'college_name', 'responses', 'recommendations', 'created_at']
        read_only_fields = ['college', 'recommendations', 'created_at']
        
    def validate(self, data):
        """
        Check that a student with the same student_id does not already exist for this college.
        Also, fetch the college instance and pass it to the create method.
        """
        college_name = data.get('college_name')
        student_id = data.get('student_id')
        
        try:
            college = College.objects.get(name=college_name)
        except College.DoesNotExist:
            raise serializers.ValidationError(f"College with name '{college_name}' does not exist.")

        if Student.objects.filter(college=college, student_id=student_id).exists():
            raise serializers.ValidationError(
                f"A student with ID '{student_id}' already exists in college '{college_name}'."
            )
        
        data['college_instance'] = college
        return data

    def create(self, validated_data):
        """
        Create a new student instance using the validated data.
        """
        college_instance = validated_data.pop('college_instance')
        validated_data.pop('college_name', None)
        
        student = Student.objects.create(college=college_instance, **validated_data)
        return student

class StudentRecommendationSerializer(serializers.ModelSerializer):
    college = CollegeSerializer(read_only=True)
    
    class Meta:
        model = Student
        fields = ['student_id', 'name', 'department', 'semester', 'college', 'recommendations']

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']

class CollegeUserSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    college = CollegeSerializer(read_only=True)
    
    class Meta:
        model = CollegeUser
        fields = ['id', 'user', 'college']
