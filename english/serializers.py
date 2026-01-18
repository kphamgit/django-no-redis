from rest_framework import serializers
#from .models import Note
from api.models import Unit, Quiz, Question, Category, Level
from django.contrib.auth.models import User

class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = ["id", "quiz_id", "question_number", "content", "format", "answer_key", "instructions", 
        "prompt", "audio_str", "score", "button_cloze_options", "timeout", "hint", "explanation"]
        #fields = '__all__'
        

class QuizSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quiz
        fields = ["id", "unit_id", "name", "quiz_number"]
        #extra_kwargs = {
        #    "questions": {"required": False}  # Make the "questions" field optional
        #}

class UnitSerializer(serializers.ModelSerializer):
    #quizzes = QuizSerializer(many=True, read_only=True)
    class Meta:
        model = Unit
        fields = ["id", "category_id", "name", "unit_number"]
        #extra_kwargs = {
        #    "units": {"required": False}  # Make the "questions" field optional
        #}

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "level_id", "name", "category_number"]
        
class LevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ["id", "name", "level_number"]
        
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username",]

