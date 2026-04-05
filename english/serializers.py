from rest_framework import serializers
#from .models import Note
from api.models import Unit, Quiz, Question, Category, Level, VideoSegment, DictEntry, PartOfSpeech, Sense, Example, Idiom
from django.contrib.auth.models import User

class QuestionSerializer(serializers.ModelSerializer):
    #video_segment = serializers.PrimaryKeyRelatedField(queryset=VideoSegment.objects.all(), required=False, allow_null=False)
    class Meta:
        model = Question
        fields = ["id", "quiz_id", "video_segment_id", "question_number", "content", "format", "answer_key", "instructions", 
        "prompt", "audio_str", "score", "button_cloze_options", "timeout", "hint", "explanation"]
        #fields = '__all__'
        


        
"""
class QuizSerializer(serializers.ModelSerializer):
    video_segments = VideoSegmentSerializer(many=True, read_only=True)  # Use the nested serializer

    class Meta:
        model = Quiz
        fields = ["id", "unit_id", "name", "quiz_number", "video_url", "questions", "video_segments"]

        extra_kwargs = {
           "questions": {"required": False},  # Make the "questions" field optional
           "video_segments": {"required": False}  # Make the "video_segments" field optional
        }
"""

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
        fields = ["id", "name", "level_number", "categories"]
        
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
            #str(question.question_number) for question in obj.video_segment_questions.all()
            str(question.id) for question in obj.video_segment_questions.all()
        )
        return question_numbers
        
class QuizSerializer(serializers.ModelSerializer):
    video_segments = VideoSegmentSerializer(many=True, read_only=True)  # Use the nested serializer
    class Meta:
        model = Quiz
        #fields = ["id", "unit_id", "name", "quiz_number", "video_url", "questions"]
        fields = ["id", "unit_id", "name", "quiz_number", "video_url", "questions", "video_segments"]
        
        extra_kwargs = {
           "questions": {"required": False},  # Make the "questions" field optional
           "video_segments": {"required": False}  # Make the "video_segments" field optional
        }

class VideoSegmentIdSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoSegment
        fields = ['id']  # Only include the 'id' field


class ExampleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Example
        fields = ["id", "sense_id", "example_number", "difficulty_level", "sentence", "translation", "grammar_point"]
        extra_kwargs = {
            "sense_id": {"required": False},  # Make the "sense_id" field optional
            # because sense_id will be set in the create method of SenseSerializer when creating Example objects from the nested data
        }  

class SenseSerializer(serializers.ModelSerializer):
    examples = ExampleSerializer(many=True, required=False)  # Use the nested serializer for examples, and make it optional
    class Meta:
        model = Sense
        fields = ["id", "pos_id", "sense_number", "definition", "cross_reference", "grammar", "related_words", "examples"]
        extra_kwargs = {
            "pos_id": {"required": False},  # Make the "pos_id" field optional
            # because pos_id will be set in the create method of PartOfSpeechSerializer when creating Sense objects from the nested data
        }
        
    def create(self, validated_data):
        examples_data = validated_data.pop("examples", [])   # pop should happend before creating the Sense object,
        # note: pop remove the "examples" key from validated_data, so that it won't cause an error
        # when creating the Sense object with the remaining validated_data
        sense = Sense.objects.create(**validated_data) 
        # now use the examples_data (popped from validated_data above) to create Example objects,
        for example_data in examples_data:
            Example.objects.create(sense=sense, **example_data)
            
        return sense
    
class IdiomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Idiom
        fields = ["id", "pos_id", "phrase", "translation"]
        
        
#   fields = ["id", "head_word", "hyphenation", "pron_code", "amevar_pron", "frequency", "part_of_speech", "grammar", "senses"]
class PartOfSpeechSerializer(serializers.ModelSerializer):
    senses = SenseSerializer(many=True)
    idioms = IdiomSerializer(many=True, required=False)  # Use the nested serializer for idioms, and make it optional
    class Meta:
        model = PartOfSpeech
        unique_together = ("dict_entry", "name")  # Ensure that the combination of dict_entry and name is unique
        fields = ["name", "dict_entry_id", "pron_code", "amevar_pron", "frequency", "grammar", "senses", "idioms"]
        extra_kwargs = {
            "pron_code": {"required": False},
        }
    
    def create(self, validated_data):
        senses_data = validated_data.pop("senses", [])
        idioms_data = validated_data.pop("idioms", [])
        pos = PartOfSpeech.objects.create(**validated_data)
        for sense_data in senses_data:
            sense_data['pos'] = pos  # set the pos field of sense_data to the PartOfSpeech object we just created
            SenseSerializer().create(sense_data)
        
        for idiom_data in idioms_data:
            idiom_data['pos'] = pos
            IdiomSerializer().create(idiom_data)
            
        return pos
    
    
class DictEntrySerializer(serializers.ModelSerializer):
    part_of_speeches = PartOfSpeechSerializer(many=True)  # Use the nested serializer
    class Meta:
        model = DictEntry
        fields = ["head_word", "source", "part_of_speeches"]
   
    def create(self, validated_data):
        part_of_speeches_data = validated_data.pop("part_of_speeches", [])
        dict_entry = DictEntry.objects.create(**validated_data)
        for pos_data in part_of_speeches_data:
            pos_data['dict_entry'] = dict_entry
            PartOfSpeechSerializer().create(pos_data)
        return dict_entry
    
    