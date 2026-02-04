from rest_framework import serializers
#from .models import Note
from api.models import Unit, Quiz, Question, Category, Level, VideoSegment
from django.contrib.auth.models import User

class QuestionSerializer(serializers.ModelSerializer):
    #video_segment = serializers.PrimaryKeyRelatedField(queryset=VideoSegment.objects.all(), required=False, allow_null=False)
    class Meta:
        model = Question
        fields = ["id", "quiz_id", "video_segment_id", "question_number", "content", "format", "answer_key", "instructions", 
        "prompt", "audio_str", "score", "button_cloze_options", "timeout", "hint", "explanation"]
        #fields = '__all__'
        

class QuizSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quiz
        #fields = ["id", "unit_id", "name", "quiz_number", "video_url", "questions"]
        fields = ["id", "unit_id", "name", "quiz_number", "video_url", "questions"]
        
        extra_kwargs = {
           "questions": {"required": False}  # Make the "questions" field optional
        }
        


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
        
class VideoSegmentSerializer(serializers.ModelSerializer):
    # define a custom field for question_numbers (there's no field with this name in the model)
    question_numbers = serializers.SerializerMethodField()
    class Meta:
        model = VideoSegment
        fields = ["id", "quiz_id", "segment_number", "start_time", "end_time", "question_numbers"]
        
    def get_question_numbers(self, obj):     # will be automatically called to get the value for question_numbers
        # Generate the question_numbers string
        question_numbers = ', '.join(
            str(question.question_number) for question in obj.video_segment_questions.all()
        )
        return question_numbers
        
class VideoSegmentIdSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoSegment
        fields = ['id']  # Only include the 'id' field

