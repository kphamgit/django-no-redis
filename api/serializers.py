from django.contrib.auth.models import User
from rest_framework import serializers
from .models import Note, Category, Level, Unit, Quiz, Question, QuestionAttempt, QuizAttempt
from english.serializers import QuizSerializer

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "password"]
        extra_kwargs = {"password": {"write_only": True}}

    def create(self, validated_data):
        print(validated_data)
        user = User.objects.create_user(**validated_data)
        return user

class QuizAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizAttempt
        fields = ["id", "quiz_id", "user_name",  "score", "created_at", "updated_at", "completion_status", "errorneous_questions", "review_state"]
        
class QuestionAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionAttempt
        fields = ["id", "question_id", "quiz_attempt_id", "error_flag", "score",  "completed", "question_id"]

  #question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="question_attempts")
 
class UnitWithQuizzesSerializer(serializers.ModelSerializer):
    quizzes = QuizSerializer(many=True, read_only=True)
    class Meta:
        model = Unit
        fields = ["id", "category_id", "name", "unit_number", "quizzes"]
        #extra_kwargs = {
        #    "quizzes": {"required": False}  # Make the "questions" field optional
        #}
             
class CategoryWithUnitsSerializer(serializers.ModelSerializer):
    units = UnitWithQuizzesSerializer(many=True, read_only=True)
    class Meta:
        model = Category
        fields = ["id", "category_id", "name", "category_number", "units"]
        extra_kwargs = {
            "units": {"required": False}  # Make the "questions" field optional
        }
        
class CategoryWithoutUnitsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "level_id", "name", "category_number"]

class LevelWithCategoriesSerializer(serializers.ModelSerializer):
    categories = CategoryWithoutUnitsSerializer(many=True, read_only=True)
    class Meta:
        model = Level
        fields = ["id", "name", "level_number", "categories"]
        #extra_kwargs = {"author": {"read_only": True}}
        extra_kwargs = {
            "categories": {"required": False}  # Make the "questions" field optional
        }
    