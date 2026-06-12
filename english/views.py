# Create your views here.
from django.shortcuts import render
from api.models import Question, Quiz, Unit, Level, Category, QuizAttempt, QuestionAttempt, VideoSegment, DictEntry, Sense, Assignment, AssignmentStudent
from .serializers import CategorySerializer, UnitSerializer, QuizSerializer, QuestionSerializer, CardSerializer, \
    LevelSerializer, VideoSegmentSerializer, VideoSegmentIdSerializer, DictEntrySerializer
from api.serializers import QuizAttemptSerializer, QuestionAttemptSerializer, CategoryWithUnitsSerializer, \
    LevelWithCategoriesSerializer, UnitWithQuizzesSerializer
from .serializers import UserSerializer, SenseSerializer
from django.contrib.auth.models import User
from rest_framework import generics
from rest_framework.decorators import api_view
from rest_framework.permissions import IsAuthenticated, AllowAny

from .utils import read_viet_dict
from .utils import scrape_longman_url

import boto3
from botocore.config import Config # ⬅️ Import this

import azure.cognitiveservices.speech as speechsdk
from azure.storage.blob import BlobServiceClient, ContentSettings
from django.conf import settings

from django.views.decorators.csrf import csrf_exempt

import json

# import spacy
#load spaCy model (globally) once when the server starts to optimize performance
# nlp = spacy.load("en_core_web_sm")

# Create your views here.
   
#  VIEWS

from django.http import JsonResponse
from django.views.decorators.csrf import get_token

class CategoryCreateView(generics.CreateAPIView):
    #print("********* CategoryCreateView called")
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]
    queryset = Category.objects.all()  # Add this line
    #print("********* CategoryCreateView called")
    def perform_create(self, serializer):
        #print("********* CategoryCreateView perform_create, request data:", self.request.data)
        if serializer.is_valid():
            serializer.save(
                category_number=self.request.data.get('category_number'),
                name=self.request.data.get('name')
            )
        else:
            print(serializer.errors)

class LevelListView(generics.ListAPIView):
    serializer_class = LevelSerializer  # Use the serializer with sub_categories by default
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        # Fetch all categories, prefetching sub_categories for optimization
        return Level.objects.order_by('level_number')
    
class UserListView(generics.ListAPIView):
    serializer_class = UserSerializer  # Use the serializer with sub_categories by default
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        # Fetch all categories, prefetching sub_categories for optimization
        return User.objects.all().order_by('id')


class CategoryListView(generics.ListAPIView):
    serializer_class = CategorySerializer  # Use the serializer with sub_categories by default
    permission_classes = [IsAuthenticated]
    #print("ENGLISH CategoryListView ****** called")
    def get_queryset(self):
        # Fetch all categories, prefetching sub_categories for optimization, filter by pk
        pk = self.kwargs.get('pk')
        #print("ENGLISH CategoryListView ****** called, pk", pk)
        return Category.objects.filter(level_id=pk).order_by('category_number')

class UnitListView(generics.ListAPIView):
    serializer_class = UnitSerializer  # Use the serializer with sub_categories by default
    permission_classes = [IsAuthenticated]
    #print("ENLGISH UnitListView ****** called")
    def get_queryset(self):
        pk = self.kwargs.get('pk')
        # Fetch all categories, prefetching sub_categories for optimization
        return Unit.objects.filter(category_id=pk).order_by('unit_number')
    
class QuizListView(generics.ListAPIView):
    serializer_class = QuizSerializer  # Use the serializer with sub_categories by default
    permission_classes = [IsAuthenticated]
    #print("ENLGISH QuizListView ****** called")
    def get_queryset(self):
        # Fetch all categories, prefetching sub_categories for optimization
        pk = self.kwargs.get('pk')
        return Quiz.objects.filter(unit_id=pk).order_by('quiz_number')


class VideoSegmentListView(generics.ListAPIView):
    serializer_class = VideoSegmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        pk = self.kwargs.get('pk')
        query_set = VideoSegment.objects.filter(quiz_id=pk).prefetch_related('video_segment_questions').order_by('segment_number')
        #print("VideoSegmentListView get_queryset, SQL Query:", query_set.query)  # Debugging SQL query
        #print("VideoSegmentListView get_queryset, query_set:", query_set)
        return query_set

class QuestionListView(generics.ListAPIView):
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]
    #permission_classes = [AllowAny]

    def get_queryset(self):
        pk = self.kwargs.get('pk')
        queryset = Question.objects.filter(quiz_id=pk).order_by('question_number')
        return queryset

class QuestionPartialListView(generics.GenericAPIView):
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]

    
    def post(self, request, *args, **kwargs):
        print(" ******* QuestionPartialListView called.........")
        pk = self.kwargs.get('pk')
        # starting_question_number = self.kwargs.get('starting_question_number')
        
        data = json.loads(request.body)
        quiz_attempt_id = data.get('quiz_attempt_id', 'default_id')
        # print("Received quiz_attempt_id:", quiz_attempt_id)
        
        questions = Question.objects.filter(
            quiz_id=pk,
            question_number__gte=starting_question_number
        ).order_by('question_number')[:3]
        
        has_more = Question.objects.filter(
            quiz_id=pk,
            question_number__gt=starting_question_number + 2
        ).exists() if questions else False
        
        # if no more questions, retrieve quiz attempt
        if not has_more:
            try:
                quiz_attempt = QuizAttempt.objects.get(id=quiz_attempt_id)
                # retrieve errorneous question attempts for this quiz attempt
                erroneous_question_attempts = quiz_attempt.errorneous_questions.split(",") if quiz_attempt.errorneous_questions else []
                # print(f"No more questions, but Quiz attempt {quiz_attempt_id} has erroneous questions: {erroneous_question_attempts}")
                
                
            except QuizAttempt.DoesNotExist:
                print(f"QuestionPartialListView Quiz attempt with ID {quiz_attempt_id} not found.")
                
        return Response({
            "questions": QuestionSerializer(questions, many=True).data,
            "has_more": has_more,
        })
        
class QuestionRangeListView(generics.GenericAPIView):
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]

    
    def post(self, request, *args, **kwargs):
        print(" ******* QuestionPartialListView called.........")
        pk = self.kwargs.get('pk')
        starting_question_number = self.kwargs.get('starting_question_number')
        print("QuestionRangeListView, starting_question_number:", starting_question_number)
        number_of_questions = self.kwargs.get('number_of_questions')
        # print("QuestionRangeListView, number_of_questions:", number_of_questions)
        
        #data = json.loads(request.body)
        #quiz_attempt_id = data.get('quiz_attempt_id', 'default_id')
        # print("Received quiz_attempt_id:", quiz_attempt_id)
        
        questions = Question.objects.filter(
            quiz_id=pk,
            question_number__gte=starting_question_number
        ).order_by('question_number')[:number_of_questions]
        
        if questions.exists():
            return Response({
            "questions": QuestionSerializer(questions, many=True).data,
        })
        else:
            return Response({"questions": None})

        

def create_azure_audio(text, language='en'):
    VOICE_MAP = {
        'en': 'en-US-JennyNeural',
        'fr': 'fr-FR-DeniseNeural',
    }
    voice_name = VOICE_MAP.get(language, 'en-US-JennyNeural')  # Ensure 'language' is passed or defaults to 'en'
    container_name = "tts-audio"
    if language == 'en':
        full_blob_name = f"{text}.mp3"
    else:  # french
        full_blob_name = f"fr_{text}.mp3"
   
    # 1. Initialize Blob Client
    blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=full_blob_name)

    # 2. Check if it already exists
    if blob_client.exists():
        # Return the existing URL immediately
        # print(f"Audio already exists for text: {text}, skipping synthesis.")
        return 

    # 3. If it doesn't exist, proceed with synthesis
    speech_config = speechsdk.SpeechConfig(
        subscription=settings.AZURE_SPEECH_KEY, 
        region=settings.AZURE_SERVICE_REGION
    )
    speech_config.speech_synthesis_voice_name = voice_name
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
    )
    
    # Synthesize to memory
    pull_stream = speechsdk.audio.PullAudioOutputStream()
    audio_config = speechsdk.audio.AudioOutputConfig(stream=pull_stream)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        #print("Audio synthesis completed successfully for text:", text)
        # 4. Upload the new audio
        blob_client.upload_blob(
            result.audio_data, 
            overwrite=True,
            content_settings=ContentSettings(content_type='audio/mpeg')
        )
    else:
        print("Audio synthesis failed for text:", text, " Reason:", result.reason)
      
class QuestionCreateView(generics.ListCreateAPIView):
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]
    
    def perform_create(self, serializer):
        #print("QuestionCreateView, perform_create, request data:", self.request.data)
        if serializer.is_valid():
            #serializer.save()
            #kpham: NO NEED for explicit fields since all are included in serializer
            print(" content_language in request data:", self.request.data.get('content_language', 'en'))   
            serializer.save( 
                question_number=self.request.data.get('question_number'),
                format=self.request.data.get('format'),
                content=self.request.data.get('content'),
                content_language=self.request.data.get('content_language', 'en'),
                quiz_id=self.request.data.get('quiz_id'),
                answer_key=self.request.data.get('answer_key'),
                instructions=self.request.data.get('instructions'),
                prompt=self.request.data.get('prompt'),
                audio_str=self.request.data.get('audio_str'),
                button_cloze_options=self.request.data.get('button_cloze_options', None),
                video_segment_id=self.request.data.get('video_segment_id', None),
            )
            if self.request.data.get('format') == '6' or self.request.data.get('format') == '3':
                #print ("QuestionCreateView format = 6 ") # word scramble or button_select
                if self.request.data.get('content_language') in ['en', 'fr']:
                    scrambled_words = self.request.data.get('content').split("/")  # Assuming the content is a comma-separated string of scrambled words
                    #print("Scrambled words:", scrambled_words)
                    for word in scrambled_words:
                        # print(f"**************** Creating Azure audio for word: {word}")
                        create_azure_audio(word, language=self.request.data.get('content_language', 'en'))
                    
            if self.request.data.get('format') == '2':   # button_select or button_select_cloze
                if (self.request.data.get('content_language') in ['en', 'fr']):
                    cloze_options = self.request.data.get('button_cloze_options', None)
                    if cloze_options:
                        cloze_options_list = cloze_options.split("/")
                        #print("Cloze options:", cloze_options_list)
                        for option in cloze_options_list:
                            # print(f"Creating Azure audio for cloze option: {option}")
                            create_azure_audio(option, language=self.request.data.get('content_language', 'en'))
                        
        else:
            print(serializer.errors)

    #fields = ["id", "unit_id", "name", "quiz_number", "questions"]
class QuizCreateView(generics.ListCreateAPIView):
    serializer_class = QuizSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        #print("QuizCreateView perform_create, request data:", self.request.data)
        if serializer.is_valid():
            serializer.save(
                unit_id=self.request.data.get('unit_id'),
                name=self.request.data.get('name'),
                video_url=self.request.data.get('video_url'),
                quiz_number=self.request.data.get('quiz_number'),
            )
        else:
            print(serializer.errors)
            
class CardCreateView(generics.ListCreateAPIView):
    serializer_class = CardSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        #print("QuizCreateView perform_create, request data:", self.request.data)
        if serializer.is_valid():
            serializer.save(
                quiz_id=self.request.data.get('quiz_id'),
                text=self.request.data.get('text'),
                difficulty=self.request.data.get('difficulty', 0),
                next_review_at=self.request.data.get('next_review_at'),
                user_id=self.request.data.get('user_id'),
                easiness=self.request.data.get('easiness', 2.5),
                interval=self.request.data.get('interval', 1),
                repetitions=self.request.data.get('repetitions', 0),
            )
        else:
            print(serializer.errors)

class VideoSegmentCreateView(generics.ListCreateAPIView):
    from .serializers import VideoSegmentSerializer
    serializer_class = VideoSegmentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        #print("VideoSegmentCreateView perform_create, request data:", self.request.data)
        if serializer.is_valid():
            serializer.save(
                quiz_id=self.request.data.get('quiz_id'),
                start_time=self.request.data.get('start_time'),
                end_time=self.request.data.get('end_time'),
               
            )
        else:
            print(serializer.errors)

    
class UnitCreateView(generics.ListCreateAPIView):
    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        #print("UnitCreateView perform_create, request data:", self.request.data)

        #print("UnitCreateView perform_create, request data:", self.request.data)
        if serializer.is_valid():
            serializer.save(
                category_id=self.request.data.get('category_id'),
                unit_number=self.request.data.get('unit_number'),
                name=self.request.data.get('name')
            )
        else:
            print(serializer.errors)
  
           
@api_view(["GET"])
def quiz_attempt_get_question_attempts(request, pk):
    """
    List all question attempts for a quiz attempt
    """
    #print("quiz_attempt_get_question_attempts called with pk:", pk)
    try:
        quiz_attempt = QuizAttempt.objects.get(id=pk)
        question_attempts = QuestionAttempt.objects.filter(quiz_attempt_id=quiz_attempt.id).order_by('id')
         # Serialize the question attempts
        serializer = QuestionAttemptSerializer(question_attempts, many=True)
        return Response(serializer.data)
    except QuizAttempt.DoesNotExist:
        return Response({"error": "Quiz attempt not found."}, status=404)
    
    
@api_view(["GET"])
def quiz_attempt_list(request):
    """
    List all quizzes, 
    """
    quiz_attempts = QuizAttempt.objects.all()
    serializer = QuizAttemptSerializer(quiz_attempts, many=True)
    #print("****** quiz_attempt_list, serializer data:", serializer.data)
    return Response(serializer.data)

@api_view(["DELETE"])
def quiz_attempt_delete(request, pk):
    #print("quiz_attempt_delete called with pk:", pk)
    try:
        quiz_attempt = QuizAttempt.objects.get(id=pk)
        quiz_attempt.delete()
        return Response({"message": "Quiz attempt deleted successfully."})
    except QuizAttempt.DoesNotExist:
        return Response({"error": "Quiz attempt not found."}, status=404)
    
@api_view(["POST"])
def quiz_attempt_bulk_delete(request):
   
    #print("quiz_attempt_delete called with pk:", pk)
    #print("quiz_attempt_bulk_delete, request data:", request.data)
    # request data : {'ids': ['18']}
    ids = request.data.get('ids')
    #print("quiz_attempt_bulk_delete, ids to delete:", ids)
    deleted_count = 0
    for quiz_attempt_id in ids:
        try:
            #print("Deleting quiz attempt with ID:", quiz_attempt_id)
            quiz_attempt = QuizAttempt.objects.get(id=quiz_attempt_id)
            quiz_attempt.delete()
            deleted_count += 1
        except QuizAttempt.DoesNotExist:
            print(f"Quiz_attempt_bulk_delete. Quiz attempt with ID {quiz_attempt_id} not found.")
    return Response({"message": f"{deleted_count} quiz attempts deleted successfully."})    


        
class CategoryCreateView(generics.ListCreateAPIView):
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        print("********* CategoryCreateView perform_create, request data:", self.request.data)
        if serializer.is_valid():
            serializer.save(
                level_id=self.request.data.get('level_id'),
                category_number=self.request.data.get('category_number'),
                name=self.request.data.get('name')
            )
        else:
            print(serializer.errors)

class LevelCreateView(generics.CreateAPIView):
    serializer_class = LevelSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        if serializer.is_valid():
            serializer.save(level_number=self.request.data.get('level_number'),
                name=self.request.data.get('name')
            )
        else:
            print(serializer.errors)

# EDIT/UPDATE VIEWS

class QuestionCloneView(generics.CreateAPIView):
    # print("QuestionCloneView called")
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        question_id = self.kwargs.get('pk')
        queryset = Question.objects.filter(id=question_id)
        return queryset
    
    def create(self, request, *args, **kwargs):
        original_question = self.get_queryset().first()
        if original_question:
            cloned_question = Question.objects.create(
                quiz_id=original_question.quiz_id,
                question_number=original_question.question_number + 1,
                format=original_question.format,
                content=original_question.content,
                answer_key=original_question.answer_key,
                instructions=original_question.instructions,
                prompt=original_question.prompt,
                audio_str=original_question.audio_str,
                button_cloze_options=original_question.button_cloze_options,
                video_segment_id=original_question.video_segment_id,
            )
            print("Question cloned successfully, cloned question ID:", cloned_question.id)
            return Response(QuestionSerializer(cloned_question).data, status=201)
        
        return Response({"error": "Original question not found."}, status=404)

    

class QuestionEditView(generics.RetrieveUpdateAPIView):
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]
    #queryset = Question.objects.filter(question_id=question_id)  # Add this line
    #print("QuestionEditView HERE")
    def perform_update(self, serializer):
        #print("QuestionEditView, request data:", self.request.data)  # Print the raw request data
        if serializer.is_valid():
            #print("Serializer is valid")
            # Print the validated data that will be saved to the database
            #print("Fields being saved to the database:", serializer.validated_data)
            # Save the validated data to the database
            # kpham: NO NEED for explicit fields since all are included in serializer
            # however, video_segment_id is nullable, so we handle it separately
            # because it is included in validated_data only if not null
            serializer.save(video_segment_id=self.request.data.get('video_segment_id', None),)
            
            if self.request.data.get('format') == '6' or self.request.data.get('format') == '3':
                #print ("QuestionCreateView format = 6 ") # word scramble or button_select
                if self.request.data.get('content_language') in ['en', 'fr']:
                    scrambled_words = self.request.data.get('content').split("/")  # Assuming the content is a comma-separated string of scrambled words
                    #print("Scrambled words:", scrambled_words)
                    for word in scrambled_words:
                        # print(f"**************** QuestionEditView Creating Azure audio for word: {word}")
                        create_azure_audio(word, language=self.request.data.get('content_language', 'en'))
                    
            if self.request.data.get('format') == '2':   # button_select or button_select_cloze
                if (self.request.data.get('content_language') in ['en', 'fr']):
                    cloze_options = self.request.data.get('button_cloze_options', None)
                    if cloze_options:
                        cloze_options_list = cloze_options.split("/")
                        #print("Cloze options:", cloze_options_list)
                        for option in cloze_options_list:
                            # print(f"QuestionEditView Creating Azure audio for cloze option: {option}")
                            create_azure_audio(option, language=self.request.data.get('content_language', 'en'))
            

        else:
            print("Serializer errors:", serializer.errors)
            
    def get_queryset(self):
        question_id = self.kwargs.get('pk')
        #queryset = Unit.objects.filter(sub_category_id=sub_category_id).prefetch_related('quizzes')
        queryset = Question.objects.filter(id=question_id)
        #print("QuestionListView, Filtered Questions no Prefetch:", queryset)
        #print("QuestionListView, SQL Query:", queryset.query)  # Debugging SQL query
        return queryset
    
class QuizEditView(generics.RetrieveUpdateAPIView):
    serializer_class = QuizSerializer
    permission_classes = [IsAuthenticated]
    #queryset = Question.objects.filter(question_id=question_id)  # Add this line
    def perform_update(self, serializer):
        #print("request data:", self.request.data)
        if serializer.is_valid():
            #("Serializer is valid")
            serializer.save(
                name=self.request.data.get('name'),
            )
        else:
            print(serializer.errors)
            
    def get_queryset(self):
        quiz_id = self.kwargs.get('pk')
        #queryset = Unit.objects.filter(sub_category_id=sub_category_id).prefetch_related('quizzes')
        queryset = Quiz.objects.filter(id=quiz_id)
        #print("QuestionListView, Filtered Questions no Prefetch:", queryset)
        #print("QuestionListView, SQL Query:", queryset.query)  # Debugging SQL query
        return queryset
    
class QuizRetrieveView(generics.RetrieveAPIView):
    serializer_class = QuizSerializer

    def get_queryset(self):
        quiz_id = self.kwargs.get('pk')
        queryset = Quiz.objects.filter(id=quiz_id)
        return queryset
    
class LevelRetrieveView(generics.RetrieveAPIView):
    # serializer_class = LevelSerializer
    serializer_class = LevelWithCategoriesSerializer   # only return id field
    """
     levels = Level.objects.order_by('level_number')
    serializer = LevelWithCategoriesSerializer(levels, many=True)
    print("******** level_list serializer.data:", serializer.data)
    """

    def get_queryset(self):
        level_id = self.kwargs.get('pk')
        queryset = Level.objects.filter(id=level_id).prefetch_related('categories')
        # print("LevelRetrieveView ******* get_queryset, SQL Query:", queryset.query)  # Debugging SQL query
        # print("LevelRetrieveView ******* get_queryset, queryset:", queryset)
        return queryset
   
class CategoryRetrieveView(generics.RetrieveAPIView):
    #print("CategoryRetrieveView called....")
    # serializer_class = LevelSerializer
    serializer_class = CategoryWithUnitsSerializer   # only return id field
    """
     levels = Level.objects.order_by('level_number')
    serializer = LevelWithCategoriesSerializer(levels, many=True)
    print("******** level_list serializer.data:", serializer.data)
    """

    def get_queryset(self):
        category_id = self.kwargs.get('pk')
        #print("CategoryRetrieveView ******* get_queryset called, category_id:", category_id)
        queryset = Category.objects.filter(id=category_id).prefetch_related('units')
        #print("CategoryRetrieveView ******* get_queryset, SQL Query:", queryset.query)  # Debugging SQL query
        #print("CategoryRetrieveView ******* get_queryset, queryset:", queryset)
        return queryset
   
class UnitRetrieveView(generics.RetrieveAPIView):
    # print("UnitRetrieveView called....")
    # serializer_class = LevelSerializer
    serializer_class = UnitWithQuizzesSerializer   # only return id field

    def get_queryset(self):
        unit_id = self.kwargs.get('pk')
        queryset = Unit.objects.filter(id=unit_id).prefetch_related('quizzes')
        # print("UnitRetrieveView ******* get_queryset, SQL Query:", queryset.query)  # Debugging SQL query
        return queryset
   
   
class VideoSegmentRetrieveView(generics.RetrieveAPIView):
    #serializer_class = VideoSegmentSerializer
    serializer_class = VideoSegmentSerializer   # only return id field
    permission_classes = [IsAuthenticated]
   
    def get_queryset(self):
        pk = self.kwargs.get('pk')
        #("VideoSegmentRetrieveView ****** get_queryset, segment_number:", segment_number)
        queryset = VideoSegment.objects.filter(pk=pk)
        return queryset
    
class VideoSegmentRetrieveByNumberView(generics.RetrieveAPIView):
    #serializer_class = VideoSegmentSerializer
    serializer_class = VideoSegmentIdSerializer   # only return id field
    permission_classes = [IsAuthenticated]
    lookup_field = 'segment_number'

    def get_queryset(self):
        quiz = self.kwargs.get('pk')
        # since segment_number is not unique across all video segments, we filter by quiz_id first, then segment_number
        temp_queryset = VideoSegment.objects.filter(quiz_id=quiz)
        # then we will use lookup_field to filter by segment_number
        queryset = temp_queryset.filter(segment_number=self.kwargs.get('segment_number'))
        #segment_number = self.kwargs.get('segment_number')
        #("VideoSegmentRetrieveView ****** get_queryset, segment_number:", segment_number)
        #queryset = VideoSegment.objects.filter(segment_number=segment_number)
        return queryset
    
class VideoSegmentEditView(generics.RetrieveUpdateAPIView):
    serializer_class = VideoSegmentSerializer
    permission_classes = [IsAuthenticated]

    def perform_update(self, serializer):
        #print("request data:", self.request.data)
        if serializer.is_valid():
            #print("Serializer is valid")
            serializer.save(
                start_time=self.request.data.get('start_time'),
                end_time=self.request.data.get('end_time'),
           
            )
        else:
            print(serializer.errors)
            
    def get_queryset(self):
        video_segment_id = self.kwargs.get('pk')
        #print("VideoSegmentEditView ****** get_queryset, video_segment_id:", video_segment_id)
        #queryset = Unit.objects.filter(sub_category_id=sub_category_id).prefetch_related('quizzes')
        queryset = VideoSegment.objects.filter(id=video_segment_id)
        return queryset
    
class UnitEditView(generics.RetrieveUpdateAPIView):
    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated]
    #queryset = Question.objects.filter(question_id=question_id)  # Add this line
    def perform_update(self, serializer):
        print("UnitEditView request data:", self.request.data)
        if serializer.is_valid():
            print("Serializer is valid")
            serializer.save(
                name=self.request.data.get('name'),
            )
        else:
            print(serializer.errors)
            
    def get_queryset(self):
        unit_id = self.kwargs.get('pk')
        #queryset = Unit.objects.filter(sub_category_id=sub_category_id).prefetch_related('quizzes')
        queryset = Unit.objects.filter(id=unit_id)
        #print("QuestionListView, Filtered Questions no Prefetch:", queryset)
        #print("QuestionListView, SQL Query:", queryset.query)  # Debugging SQL query
        return queryset


class CategoryEditView(generics.RetrieveUpdateAPIView):
   
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]
    def perform_update(self, serializer):
        print("perform_update request data:", self.request.data)
        if serializer.is_valid():
            print("Serializer is valid")
            serializer.save(
                name=self.request.data.get('name'),
            )
        else:
            print(serializer.errors)
            
    def get_queryset(self):
        category_id = self.kwargs.get('pk')
        queryset = Category.objects.filter(id=category_id)
        #print("QuestionListView, Filtered Questions no Prefetch:", queryset)
        #print("QuestionListView, SQL Query:", queryset.query)  # Debugging SQL query
        return queryset

class LevelEditView(generics.RetrieveUpdateAPIView):
    serializer_class = LevelSerializer
    permission_classes = [IsAuthenticated]
    def perform_update(self, serializer):
        print("LevelEditView request data:", self.request.data)
        if serializer.is_valid():
            print("Serializer is valid")
            serializer.save(
                name=self.request.data.get('name'),
            )
        else:
            print(serializer.errors)
            
    def get_queryset(self):
        level_id = self.kwargs.get('pk')
        #print("XXXXXX category_id:", category_id)
        #queryset = Unit.objects.filter(sub_category_id=sub_category_id).prefetch_related('quizzes')
        queryset = Level.objects.filter(id=level_id)
        #print("LevelEditView, Filtered Questions no Prefetch:", queryset)
        #print("LevelEditView, SQL Query:", queryset.query)  # Debugging SQL query
        return queryset
    
from rest_framework.response import Response
from rest_framework.views import APIView

# renumber views
class LevelRenumberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        id_numbers = self.request.data.get('id_number_pairs')
        # Convert the JSON string representation of the list to an actual list
        import ast
        id_numbers = ast.literal_eval(id_numbers)
        
        for index, level_id in enumerate(id_numbers, start=1):  # Start numbering from 1
            try:
                level = Level.objects.get(id=level_id)
                level.level_number = index  # Use the index as the new number
                level.save()
            except Level.DoesNotExist:
                print(f"Level with ID {level_id} does not exist.")
                
        return Response({"message": "Level renumbered successfully."})

class CategoryRenumberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        id_numbers = self.request.data.get('id_number_pairs')
        # Convert the JSON string representation of the list to an actual list
        import ast
        id_numbers = ast.literal_eval(id_numbers)
        
        for index, category_id in enumerate(id_numbers, start=1):  # Start numbering from 1
            try:
                category = Category.objects.get(id=category_id)
                category.category_number = index  # Use the index as the new number
                category.save()
            except Category.DoesNotExist:
                print(f"Category with ID {category_id} does not exist.")
                
        return Response({"message": "Category renumbered successfully."})
            
class UnitRenumberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        id_numbers = self.request.data.get('id_number_pairs')
        # Convert the JSON string representation of the list to an actual list
        import ast
        id_numbers = ast.literal_eval(id_numbers)
        
        for index, unit_id in enumerate(id_numbers, start=1):  # Start numbering from 1
           
            try:
                unit = Unit.objects.get(id=unit_id)
                unit.unit_number = index  # Use the index as the new number
                unit.save()
            except Unit.DoesNotExist:
                print(f"Unit with ID {unit_id} does not exist.")
                
        return Response({"message": "Units renumbered successfully."})
            

class QuizRenumberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        id_numbers = self.request.data.get('id_number_pairs')
        # Convert the JSON string representation of the list to an actual list
        import ast
        id_numbers = ast.literal_eval(id_numbers)
        
        for index, quiz_id in enumerate(id_numbers, start=1):  # Start numbering from 1
        
            try:
                quiz = Quiz.objects.get(id=quiz_id)
                quiz.quiz_number = index  # Use the index as the new number
                quiz.save()
            except Quiz.DoesNotExist:
                print(f"Quiz with ID {quiz_id} does not exist.")
                
        return Response({"message": "Questions renumbered successfully."})
            
class VideoSegmentRenumberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # print("request data:", self.request.data)
        #request data: {'data_type': 'question', 'id_number_pairs': '[10,4,5,6]'}
        id_numbers = self.request.data.get('id_number_pairs')
        # Convert the string representation of the list to an actual list
        import ast
        id_numbers = ast.literal_eval(id_numbers)
        # print("after .... conversion: id_number_pairs:", id_numbers)
      
        for index, video_segment_id in enumerate(id_numbers, start=1):  # Start numbering from 1
            #question_id = question_id
            try:
                video_segment = VideoSegment.objects.get(id=video_segment_id)
                video_segment.segment_number = index  # Use the index as the new number
                video_segment.save()
                #print(f"Updated Question ID {question_id} to new number {index}")
            except VideoSegment.DoesNotExist:
                print(f"Video Segment with ID {video_segment_id} does not exist.")
                
        return Response({"message": "VideoSegments renumbered successfully."})
    
class QuestionRenumberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # print("request data:", self.request.data)
        #request data: {'data_type': 'question', 'id_number_pairs': '[10,4,5,6]'}
        id_numbers = self.request.data.get('id_number_pairs')
        # Convert the string representation of the list to an actual list
        import ast
        id_numbers = ast.literal_eval(id_numbers)
        # print("after .... conversion: id_number_pairs:", id_numbers)
      
        for index, question_id in enumerate(id_numbers, start=1):  # Start numbering from 1
            #question_id = question_id
            try:
                question = Question.objects.get(id=question_id)
                question.question_number = index  # Use the index as the new number
                question.save()
                # print(f"Updated Question ID {question_id} to new number {index}")
            except Question.DoesNotExist:
                print(f"Question with ID {question_id} does not exist.")
                
        return Response({"message": "Questions renumbered successfully."})
            
#from django.apps import apps
    
class ItemDeleteView(generics.DestroyAPIView):
    serializer_class = QuizSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        id = self.kwargs.get('pk')
        # retrieve data_type from query parameters
        # print("ItemDeleteView .... request data:", self.request)
        
        data_type = self.request.query_params.get('data_type', 'question').lower() # Default to 'question' if not provided
        #data_type = self.request.data.get('data_type', 'Question') # Default to 'Question' if not provided
        queryset = None
        # print("ItemDeleteView get_queryset, data_type:", data_type, ", id:", id)
        if data_type == 'question':
            queryset = Question.objects.filter(id=id) 
        elif data_type == 'quiz':
            # print("ItemDeleteView Quiz Delete .... id:", id)
            queryset = Quiz.objects.filter(id=id)
        elif data_type == 'unit':
            queryset = Unit.objects.filter(id=id)
        elif data_type == 'level':
            queryset = Level.objects.filter(id=id)
        elif data_type == 'category':
            queryset = Category.objects.filter(id=id)
        elif data_type == 'video_segment':
            queryset = VideoSegment.objects.filter(id=id)
            
        
        # print("ItemDeleteView get_queryset, queryset:", queryset)
        
        return queryset
    
@api_view(["POST"])
def move_quiz(request, pk):
    # print("move_quiz called with quiz_id:", pk, " request.data:", request.data)
    try:
        quiz = Quiz.objects.get(id=pk)
        new_unit_id = request.data.get('new_unit_id', None)
        if new_unit_id is None:
            return Response({
                "error": "new_unit_id is required in the request data."
            }, status=400)
        new_unit = Unit.objects.get(id=new_unit_id)
        quiz.unit = new_unit
        quiz.save()
        return Response({
            "message": f"Quiz {quiz.name} moved to unit {new_unit.name} successfully."
        })
    except Quiz.DoesNotExist:
        return Response({
            "error": "Quiz not found for the given quiz_id."
        }, status=404)
    except Unit.DoesNotExist:
        return Response({
            "error": "Unit not found for the given new_unit_id."
        }, status=404)
        
@api_view(["POST"])
def assign_quiz(request, pk):
    # print studentNames from request.data
    # print("assign_quiz called with quiz_id:", pk, " request.data:", request.data)
    # studentNames is a string separated by commas, we convert it to a list
    user_names_str = request.data.get('studentNames', '')
    user_names = [name.strip() for name in user_names_str.split(',') if name.strip()]
    # for each student name, create a user object if it doesn't exist,
    # create an assignment object 
    # and assign it to each user in 
    # print("move_quiz called with quiz_id:", pk, " request.data:", request.data)
    try:
        quiz = Quiz.objects.get(id=pk)
        # get the unit for the quiz
        unit = quiz.unit
        # get the category_id for the unit
        category = unit.category
        # print("********** Quiz:", quiz.id, " Unit:", unit.name, " Category id:", category.id)
        assignment = Assignment.objects.create(quiz=quiz, category_id=category.id)
        for user_name in user_names:
            user = User.objects.filter(username=user_name).first()
            if user is None:
                # print(f"User with username {user_name} not found, skipping.")
                continue
            AssignmentStudent.objects.create(assignment=assignment, user=user)

        return Response({
            "message": f"Quiz  assigned successfully."
        })
    except Quiz.DoesNotExist:
        return Response({
            "error": "Quiz not found for the given quiz_id."
        }, status=404)
   
    
def get_audio_url(file_key):
    # Initialize the client with the v4 signature config
    s3_client = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version='s3v4') # ⬅️ Add this line
    )

    url = s3_client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
            'Key': file_key
        },
        ExpiresIn=3600
    )
    return url
    
@csrf_exempt
def get_recordings(request):
    # List objects in the S3 bucket under the "audios/recordings/" prefix
    s3_client = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME
    )
    bucket_name = settings.AWS_STORAGE_BUCKET_NAME
    prefix = "audios/recordings/"
    response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)

    recordings = []
    for obj in response.get('Contents', []):
        file_key = obj['Key']
        #print("Found audio file in S3 with key:", file_key)
        url = get_audio_url(file_key)
        recordings.append({
            'file_key': file_key,
            'audio_url': url
        })
        
    return JsonResponse({'recordings': recordings})

@csrf_exempt
def delete_audio(request):
    try:
        # Check if the request body is JSON
        if request.content_type == 'application/json':
            #print("delete_audio received JSON request body:", request.body)
            data = json.loads(request.body)
            file_key = data.get('file_key')
        else:
            # Handle form-data or x-www-form-urlencoded
            #print("delete_audio received non-JSON request, using POST parameters:", request.POST)
            file_key = request.POST.get('file_key')

        #print("delete_audio called with file_key:", file_key)

        if not file_key:
            return JsonResponse({'error': 'file_key parameter is required'}, status=400)

        # Initialize S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME

        # Delete the object from S3
        s3_client.delete_object(Bucket=bucket_name, Key=file_key)

        return JsonResponse({'status': f'Audio file with key {file_key} deleted successfully'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def batch_delete_files(request):
    try:
        # Parse the JSON payload
        # print("batch_delete_files called body:", request.body)
        file_keys = json.loads(request.body).get('file_keys', [])
        # print("batch_delete_files received file_keys:", file_keys)

        if not file_keys:
            return JsonResponse({'error': 'No file keys provided'}, status=400)

        # Initialize the S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )

        # Specify the bucket name
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME

        # Prepare the list of objects to delete
        objects_to_delete = [{'Key': key} for key in file_keys]

        # Perform the batch delete
        response = s3_client.delete_objects(
            Bucket=bucket_name,
            Delete={
                'Objects': objects_to_delete,
                'Quiet': True  # Set to False to get detailed info about deleted objects
            }
        )

        # Wrap the response in a JsonResponse
        return JsonResponse({'status': 'Batch delete completed', 'response': response})

    except Exception as e:
        # Handle any exceptions and return an error response
        return JsonResponse({'error': str(e)}, status=500)

def populate_entry(word):
    # make a list of 
    vdict_entries = read_viet_dict(word)
    # iterate throught the part of speech keys for the word
   
   
    part_of_speech_list = []
    for part_of_speech in vdict_entries[word].keys():
        part_of_speech_dict = {}
        part_of_speech_dict["name"] = part_of_speech
        senses_list = []
        for i, sense in enumerate(vdict_entries[word][part_of_speech]["senses"], start=1):
            sense_dict = {}
            sense_dict['definition'] = sense.get('def', '')
            sense_dict['sense_number'] = i
            
            examples = sense.get("examples", [])
            examples_list = []
            if examples:
                for example in examples:
                    example_dict = {}
                    example_dict["sentence"] = example
                    examples_list.append(example_dict)
            
            if examples_list:
                sense_dict['examples'] = examples_list
                    
            senses_list.append(sense_dict)
                    
        part_of_speech_dict['senses'] = senses_list
        
        # idioms
        idioms_list = []
        for i, idiom in enumerate(vdict_entries[word][part_of_speech]["idioms"], start=1):
            idiom_dict = {}
            idiom_dict['phrase'] = idiom.get('phrase', '')
            idiom_dict['translation'] = idiom.get('translation', '')
            
            idioms_list.append(idiom_dict)
                    
        part_of_speech_dict['idioms'] = idioms_list
        
        part_of_speech_list.append(part_of_speech_dict)
    
        return part_of_speech_list
    
@csrf_exempt
def delete_dictionary_entry(request):
    try:
        # Check if the request body is JSON
        # get word from request body
        if request.content_type == 'application/json':
            print("delete_dictionary_entry received JSON request body:", request.body)
            data = json.loads(request.body)
            word = data.get('word')
            source = data.get('source')
        else:
            # Handle form-data or x-www-form-urlencoded
            print("delete_dictionary_entry received non-JSON request, using POST parameters:", request.POST)
            word = request.POST.get('word')
            source = request.POST.get('source')
        
        DictEntry.objects.filter(head_word=word, source=source).delete()
        
        return JsonResponse({'status': f'Dictionary entry for word "{word}" deleted successfully.'})
       
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    
@csrf_exempt
def populate_viet_dictionary(request):
    try:
        # Check if the request body is JSON
        # get word from request body
        if request.content_type == 'application/json':
            # print("read_viet_dictionary received JSON request body:", request.body)
            data = json.loads(request.body)
            word = data.get('word')
        else:
            # Handle form-data or x-www-form-urlencoded
            # print("read_viet_dictionary received non-JSON request, using POST parameters:", request.POST)
            word = request.POST.get('word')
        
        part_of_speech_list = populate_entry(word)
        for_serialization = {}    
        for_serialization['head_word'] = word
        for_serialization['source'] = "ho-ngoc-duc-stardict"
        for_serialization['part_of_speeches'] = part_of_speech_list
        #print("**************************************************")
        #print(json.dumps(for_serialization, indent=4, ensure_ascii=False))
        
        serializer = DictEntrySerializer(data=for_serialization)
        
        if serializer.is_valid():
            serializer.save()
        else:
            # print("Serializer errors:", serializer.errors)
            # return error response if serializer is not valid
            return JsonResponse({'error': 'Failed to serialize dictionary entry.', 'details': serializer.errors}, status=400)
        
        return JsonResponse({'status': 'Vietnamese dictionary populated successfully.'})
       
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def read_dictionary(request):
    try:
        # Check if the request body is JSON
        # get word from request body
        if request.content_type == 'application/json':
            # print("read_dictionary received JSON request body:", request.body)
            data = json.loads(request.body)
            word = data.get('word')
            source = data.get('source', None)
        else:
            # Handle form-data or x-www-form-urlencoded
            print("read_dictionary received non-JSON request, using POST parameters:", request.POST)
            word = request.POST.get('word')
            source = request.POST.get('source', None)
        
        if (source):
            query = DictEntry.objects.filter(head_word__icontains=word, source=source) 
            # print("read_dictionary, query:", query)
            serializer = DictEntrySerializer(query, many=True)
        
            # print pretty printed serializer data
            print("read_dictionary, serializer data:", json.dumps(serializer.data, indent=4, ensure_ascii=False))
            if not serializer.data:
                return JsonResponse({'error': f'No dictionary entry found for word "{word}" with source "{source}".'}, status=404)
        
            return JsonResponse(serializer.data, safe=False)
        else:   # return error asking to specify source if source is not provided
            return JsonResponse({'error': 'Source dictionary is required when searching for a dictionary entry.'}, status=400)
    

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
        
    """
     # exact match — raises DoesNotExist if not found
        query = DictEntry.objects.get(head_word=word)
        serializer = DictEntrySerializer(query)

        # or, case-insensitive, returns None if not found
        #query = DictEntry.objects.filter(head_word__icontains=word).first()
        
        return JsonResponse(serializer.data)
    """
    
@csrf_exempt
def  populate_longman_dictionary(request):
    try:
        # Check if the request body is JSON
        # get word from request body
        if request.content_type == 'application/json':
            print("read_dictionary received JSON request body:", request.body)
            data = json.loads(request.body)
            word = data.get('word')
        else:
            # Handle form-data or x-www-form-urlencoded
            print("read_dictionary received non-JSON request, using POST parameters:", request.POST)
            word = request.POST.get('word')
            
        target_url = "https://www.ldoceonline.com/dictionary/" + word # Change this to your dictionary URL
        soup = scrape_longman_url(target_url)
        
        dict_entry = soup.find_all('span', class_ = lambda x: x and 'dictentry' in x)
        for_serialization = {}
        for_serialization['head_word'] = word
        for_serialization['source'] = "longman"
        part_of_speeches_list = []
        # go through each dict entry and print the html of the div with class "POS"
        # create a python dictionary to store the head word, part of speech for serialization later
        for entry in dict_entry:
            ldoce_section = entry.find('span', class_ = lambda x: x and 'ldoceEntry Entry' in x)
            # print(" found ldoce section")
           
            if ldoce_section:
                part_of_speech = ldoce_section.find('span', class_ = lambda x: x and 'POS' in x)
                if part_of_speech:
                    part_of_speech_dict = {}
                    #print(part_of_speech.prettify())
                    part_of_speech_dict['name'] = part_of_speech.get_text(strip=True)
                    # name | pron_code | amevar_pron | frequency | grammar | dict_entry_id 
                pron_code = ldoce_section.find('span', class_ = lambda x: x and 'PRON' in x)
                if pron_code:
                    part_of_speech_dict['pron_code'] = pron_code.get_text(strip=True)
                    
                american_pron_code = ldoce_section.find('span', class_ = lambda x: x and 'AMEVARPRON' in x)
                if american_pron_code:
                    part_of_speech_dict['amevar_pron'] = american_pron_code.get_text(strip=True)
                   
                grammar = ldoce_section.find('span', class_ = lambda x: x and 'GRAM' in x)
                if grammar:
                    # print("GRAM", grammar.get_text(strip=True))
                    # get the text of grammar and remove all extra spaces and newlines,
                    # also remove the surrounding square brackets if they exist
                    part_of_speech_dict['grammar'] = grammar.get_text(strip=True).replace('\n', ' ').replace('[', '').replace(']', '').strip()
                    
                frequency = ldoce_section.find('span', class_ = lambda x: x and 'FREQ' in x)
                if frequency:
                    # print(frequency.prettify())
                    part_of_speech_dict['frequency'] = frequency.get_text(strip=True)
                     
                senses = ldoce_section.find_all('span', class_ = lambda x: x and 'Sense' in x)
                senses_list = []
                for sense in senses:
                    # print("SENSE:", sense.prettify())
                    sense_dict = {}
                    
                    sense_number = sense.find('span', class_ = lambda x: x and 'sensenum span' in x)
                    if sense_number:
                        # print("sense_number:", sense_number.get_text(strip=True))
                        sense_dict['sense_number'] = sense_number.get_text(strip=True)
                    
                    definition = sense.find('span', class_ = lambda x: x and 'DEF' in x)
                    if definition:
                        # print("definition:", definition.get_text(strip=True))
                        sense_dict['definition'] = definition.get_text(strip=False)
                    
                    related_words = sense.find_all('span', class_ = lambda x: x and 'RELATEDWD' in x)
                    if related_words:
                        related_words_str = ''
                        for related_word in related_words:
                            #print("related_word:", related_word.get_text(strip=True))
                            # strip non printable characters from related_word text and 
                            text = related_word.get_text(strip=True)
                            for c in text:
                                if ord(c) > 127:
                                    print(repr(c), hex(ord(c)))
                            # print("related_word text before stripping non-printable characters:", text)
                            text = text.replace('\u2192', '').replace(',','') 
                            # remove right arrow character and any commas from the text
                            # print("related_word text after stripping non-printable characters:", text)
                            # if the text is not empty after stripping, add it to the related_words string, separated by a comma
                            if (text):
                                if related_words_str:
                                    related_words_str += '/' + text
                                else:
                                    related_words_str = text
                                    
                            #related_words.append(text)
                            #related_words_list.append(related_word.get_text(strip=True))
                        #print("related_words_str is:", related_words_str)
                        sense_dict['related_words'] = related_words_str
                        
                    #examples = sense.find_all('span', class_ = lambda x: x and 'EXAMPLE' in x)
                    examples = sense.find_all('span', class_=lambda x: x and 'EXAMPLE' in x, recursive=False)
                    examples_list = []
                    examples_length = 0
                    if examples:
                        #for example in examples:
                        for i, example in enumerate(examples, start=1):
                            example_dict = {}
                            example_dict['example_number'] = i
                            example_dict['sentence'] = example.get_text()
                            example_dict['translation'] = None
                            example_dict['grammar_point'] = None
                            examples_list.append(example_dict)
                            # 
                        sense_dict['examples'] = examples_list
                        examples_length = len(examples_list)
                        
                    #find Gramar Example
                    
                    gram_examples = sense.find_all('span', class_ = lambda x: x and 'GramExa' in x)
                    if gram_examples:
                        for i, gram_example in enumerate(gram_examples, start=examples_length + 1):
                            example_dict = {}
                            # print("gram_example:", gram_example.get_text(strip=True))
                            # get the first span as child of gram_example which contains the form of the grammar point, e.g., "be rewarded (with something)"
                            grammar_point_span = gram_example.find('span')
                            if grammar_point_span:
                                # print("grammar_point_span:", grammar_point_span.get_text(strip=True))
                                example_dict['grammar_point'] = grammar_point_span.get_text(strip=True)
                        
                            # get the EXAMPLE itself
                            example_span = gram_example.find('span', class_ = lambda x: x and 'EXAMPLE' in x)
                            if example_span:
                                # print("example_span:", example_span.get_text(strip=True))
                                example_dict['sentence'] = example_span.get_text(strip=True)
                                example_dict['example_number'] = i
                                example_dict['translation'] = None
                            
                            examples_list.append(example_dict)
                    
                            
                    # print("examples_list:", examples_list)
                            
                    sense_dict['examples'] = examples_list
                    
                    cross_reference = sense.find('span', class_ = lambda x: x and 'Crossref' in x)
                    if cross_reference:
                        # print("cross_reference:", cross_reference)
                        # look for the link inside the cross reference span and get the text of the link
                        cross_reference_link = cross_reference.find('a')
                        if cross_reference_link:
                            # look for span with class "REFHWD" inside the link and get the text of that span as the head word of the cross reference
                            cross_ref_head_word_title = cross_reference_link.find('span', class_ = lambda x: x and 'REFHWD' in x)
                            # print("ref_head_word_title:", cross_ref_head_word_title.get_text(strip=True))
                            # be rewarded (with something)
                            # 
                            # get the href attribute of the link and extract the xref head word from the URL
                            cross_ref_url = cross_reference_link['href']
                            cross_ref_head_word = cross_ref_url.split('/')[-1] # be-rewarded-with-something
                            # print("cross_ref_head_word:", cross_ref_head_word)
                            # join the title and the head word with a forward slash 
                            cross_reference_text = f"{cross_ref_head_word_title.get_text(strip=True)}/{cross_ref_head_word}"
                            # print("cross_reference_text:", cross_reference_text)
                            sense_dict['cross_reference'] = cross_reference_text
                    
                    # add sense_dict to senses_list
                    # print("sense_dict:", sense_dict)
                    senses_list.append(sense_dict)
                    # print("senses_list:", senses_list)
                    # [{'definition': 'something that you get because you have done something good orhelpfulor have worked hard', 'related_words': 'prize/benefit'}, {'definition': 'money that is offered to people for helping the police tosolveacrimeorcatchacriminal'}]
                    
                # add sesnses_list to for_serialization
                part_of_speech_dict['senses'] = senses_list
            
                part_of_speeches_list.append(part_of_speech_dict)
                                   
        for_serialization['part_of_speeches'] = part_of_speeches_list
        serializer = DictEntrySerializer(data=for_serialization)
        # for_serialization['part_of_speeches'] = part_of_speech.get_text(strip=True)
        # print(json.dumps(for_serialization, indent=4, ensure_ascii=False))
         
        
        if serializer.is_valid():
            # print("Serialized LdoceEntry:", serializer.data)
            # save to database
                serializer.save()
        else:
            print("Serializer errors:", serializer.errors)
        
                        
        return JsonResponse({'status': 'OK'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


class SenseUpdateView(generics.RetrieveUpdateAPIView):
    serializer_class = SenseSerializer
    permission_classes = [IsAuthenticated]
    # permission_classes = [AllowAny]
    def perform_update(self, serializer):
        print("request data:", self.request.data)
        if serializer.is_valid():
            print("Serializer is valid")
            serializer.save(
                definition=self.request.data.get('definition'),
            )
        else:
            print(serializer.errors)
    
    def get_queryset(self):
        sense_id = self.kwargs.get('pk')
        #queryset = Unit.objects.filter(sub_category_id=sub_category_id).prefetch_related('quizzes')
        queryset = Sense.objects.filter(id=sense_id)
        #print("QuestionListView, Filtered Questions no Prefetch:", queryset)
        #print("QuestionListView, SQL Query:", queryset.query)  # Debugging SQL query
        return queryset
    
"""
from nlp_utils import analyze_user_text

def nlp_view(request):
    user_input = request.GET.get('text', 'Hello world')
    results = analyze_user_text(user_input)
    return JsonResponse(results)


def get_tokens(text):
    # The 'doc' object holds all the token information
    doc = nlp(text)
    # Extract just the text of each token
    tokens = [token.text for token in doc]
    return tokens

def nlp_test(request):
    try:
        # Load the model
        
        # doc = nlp("Checking if spaCy works on Heroku.")
        text = "Apple is looking at buying U.K. startup for $1 billion"
        tokens = get_tokens(text)
        return JsonResponse({
            "status": "success",
            "tokens": tokens,
            "model": "en_core_web_sm"
        })
        # tokenize the text
        # Return a simple extraction
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
"""