from django.shortcuts import render

#from django.shortcuts import render
from django.contrib.auth.models import User
from rest_framework import generics
from api.serializers import UserSerializer, LevelWithCategoriesSerializer, \
     UnitWithQuizzesSerializer, QuizAttemptSerializer, QuizDetailSerializer, QuestionAttemptSerializer
from english.serializers import QuestionSerializer, UnitSerializer
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import Unit, Quiz, Question, QuizAttempt, QuestionAttempt, Level, VideoSegment, AssignmentStudent
from rest_framework.decorators import api_view
from api.utils import check_answer

from django.conf import settings

        
import json

#import redis

from rest_framework.response import Response

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django.utils.decorators import method_decorator
import os

# redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)
import json as JSON

# Use REDIS_URL from environment variables
"""
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')  # Default to localhost for development
print("Connecting to Redis at URL:", REDIS_URL)
redis_client = redis.StrictRedis.from_url(REDIS_URL, decode_responses=True)
"""

@csrf_exempt
@require_POST
def send_notification(request):
    #print("send_notification endpoint hit request", request)
    try:
        # Parse the JSON payload (remember request.body is ALWAYS in JSON string format,
        # so you need to json.loads it to convert it to a Python dict before you can access its fields)
        # print("send_notification called with request.body:", request.body)
        data = json.loads(request.body)
       
        # since Redis only accepts JSON strings, we have to convert the request.body back to a JSON string.
        # you don't want to send a request.body directly without this ROUNDABOUT converting process, 
        # because request.body is a JSON string, and if you send it directly to Redis, 
        # it will be treated as a plain string, not a JSON object, and the Node.js server won't be able 
        # to parse it correctly to access the message_type field and route the notification to the right clients.
        
        message = json.dumps(data)  # Convert entire data to JSON string
        print("Message to send with notification:", message)

        if not message:
            return JsonResponse({'error': 'Message is required'}, status=400)

        # Publish the message to the "notifications" channel
        # look in the nodejs server (with Redis) code to see how the message is 
        # consumed from the notifications channel and sent to clients via websocket
        # redis_client.publish('notifications', message)
        settings.R_CONN.publish('notifications', message)
        
        # save the message to a Redis list for record-keeping (optional)
        # settings.R_CONN.lpush('notifications_history', message)
        # settings.R_CONN.publish('notifications',json.dumps(testJson))

        return JsonResponse({'status': 'Message sent to notifications channel'})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON payload'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

import boto3
from botocore.config import Config # ⬅️ Import this

import azure.cognitiveservices.speech as speechsdk
from azure.storage.blob import BlobServiceClient, ContentSettings
from django.conf import settings

@csrf_exempt
def create_azure_audio(request):
    container_name = "tts-audio"
    full_blob_name = ""
    text = ""
    if request.content_type == 'application/json':
        print("create_azure_audio received JSON request body:", request.body)
        data = json.loads(request.body)
        full_blob_name = data.get('blob_name', 'default_name') + ".mp3"
        print("Received JSON request for create_azure_audio with full_blob_name:", full_blob_name)
        text = data.get('text', "What is that?")
    else:
            # Handle form-data or x-www-form-urlencoded
        print("create_azure_audio received non-JSON request, using POST parameters:", request.POST)
        full_blob_name = request.POST.get('blog_name') + ".mp3"
        print("Received non-JSON request for create_azure_audio with full_blob_name:", full_blob_name)
        text = request.POST.get('text', "What is that?")
        print("Received non-JSON request for create_azure_audio with text:", text)
        
    # 1. Initialize Blob Client
    blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=full_blob_name)

    # 2. Check if it already exists
    if blob_client.exists():
        # Return the existing URL immediately
        return JsonResponse({'audio_url': blob_client.url})

    print("AZURE_SPEECH_KEY:", settings.AZURE_SPEECH_KEY)
    print("AZURE_SERVICE_REGION:", settings.AZURE_SERVICE_REGION)
    # 3. If it doesn't exist, proceed with synthesis
    speech_config = speechsdk.SpeechConfig(
        subscription=settings.AZURE_SPEECH_KEY, 
        region=settings.AZURE_SERVICE_REGION
    )
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
    )
    
    # Synthesize to memory
    pull_stream = speechsdk.audio.PullAudioOutputStream()
    audio_config = speechsdk.audio.AudioOutputConfig(stream=pull_stream)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print("Audio synthesis completed successfully for text:", text)
        # 4. Upload the new audio
        blob_client.upload_blob(
            result.audio_data, 
            overwrite=True,
            content_settings=ContentSettings(content_type='audio/mpeg')
        )
        return JsonResponse({'audio_url': blob_client.url})
    
    return JsonResponse({'error': 'Audio synthesis failed'}, status=500)

"""
def create_azure_audio(text, blob_name):
    container_name = "tts-audio"
    #full_blob_name = f"{blob_name}.mp3"
    full_blob_name = "What is that.mp3"
    
    # 1. Initialize Blob Client
    blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=full_blob_name)

    # 2. Check if it already exists
    if blob_client.exists():
        # Return the existing URL immediately
        return blob_client.url

    # 3. If it doesn't exist, proceed with synthesis
    speech_config = speechsdk.SpeechConfig(
        subscription=settings.AZURE_SPEECH_KEY, 
        region=settings.AZURE_SERVICE_REGION
    )
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
    )
    
    # Synthesize to memory
    pull_stream = speechsdk.audio.PullAudioOutputStream()
    audio_config = speechsdk.audio.AudioOutputConfig(stream=pull_stream)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    test_text = "What is that?"
    result = synthesizer.speak_text_async(test_text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        # 4. Upload the new audio
        blob_client.upload_blob(
            result.audio_data, 
            overwrite=True,
            content_settings=ContentSettings(content_type='audio/mpeg')
        )
        return blob_client.url
    
    return None
"""

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
def upload_audio(request):
  # 1. Initialize the S3 client using your Django settings
    s3_client = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME
    )

    #bucket_name = settings.AWS_STORAGE_BUCKET_NAME
    audio_file = request.FILES.get('audio')
    if audio_file:
        # Inside your Django view
        audio_file = request.FILES.get('audio')
        audio_file.seek(0)  # 👈 ALWAYS add this line before uploading to S3
    
        # print("Received audio file:", audio_file.name, "size:", audio_file.size)
        s3_client.put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key="audios/recordings/" + audio_file.name,
            Body=audio_file,
            ContentType="audio/webm"  # Set the correct content type for audio files
        )
        #print("Audio file uploaded to S3 with name:", audio_file.name)
        # student_3_3_2026_10-18-44_PM.webm
        # split audio_file.name by "_" and get the first part as user name
        user_name = audio_file.name.split("_")[0]
        presigned_url = get_audio_url("audios/recordings/" + audio_file.name)
        settings.R_CONN.publish('notifications', json.dumps({
            "message_type": "recording_received",
            "content": presigned_url,
            "user_name": user_name,
        }))
        
        return JsonResponse({'status': 'Audio file uploaded successfully'})
    else:
        return JsonResponse({'error': 'No audio file provided'}, status=400)
        
class CreateUserView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [AllowAny]
    
    """
class CategoryCreate(generics.CreateAPIView):
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]

    #def get_queryset(self):
    #    user = self.request.user
    #    print("INNNNNN CategoryListCreate, user:", user)
    #    return Category.objects.all().order_by('category_number').prefetch_related('sub_categories')

    def perform_create(self, serializer):
        if serializer.is_valid():
            serializer.save(author=self.request.user)
        else:
            print(serializer.errors)
"""

@api_view(["GET"])
def level_list(request):
    #print("level_list called")
    levels = Level.objects.order_by('level_number')
    serializer = LevelWithCategoriesSerializer(levels, many=True)
    # print("******** level_list serializer.data:", serializer.data)
    return Response(serializer.data)
    

# views.py
#import io
#from django.http import HttpResponse
#from rest_framework.views import APIView
#from deepgram import DeepgramClient, SpeakOptions
#from rest_framework.decorators import permission_classes

import os
from openai import OpenAI
from django.http import HttpResponse


# Ensure OPENAI_API_KEY is in your environment variables
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@api_view(['POST'])
#@permission_classes([AllowAny])  # Allow unauthenticated access for testing
def speak(request):
    # Get text from request (optional)
    text = request.data.get("text", "This is a test of OpenAI TTS.")

    # Generate TTS
    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",  # Correct TTS model
        voice="alloy",
        input=text
    )

    # Read full audio bytes
    audio_bytes = response.read()

    # Return as MP3
    return HttpResponse(audio_bytes, content_type="audio/mpeg")

    
from django.http import StreamingHttpResponse
#from rest_framework.decorators import api_view
#from openai import OpenAI

#client = OpenAI(api_key="OPENAI_API_KEY")  # Use env variable in production
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@api_view(['POST'])
#@permission_classes([AllowAny]) 
def speak_stream(request):
    text = request.data.get("text", "Hello, this is a streaming test!")

    def stream_audio():
        # Use streaming response from OpenAI
        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text
        ) as response:
            for chunk in response.iter_bytes(chunk_size=1024):
                yield chunk

    return StreamingHttpResponse(stream_audio(), content_type="audio/mpeg")
    
from django.http import StreamingHttpResponse
from rest_framework.decorators import api_view
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@api_view(['POST'])
#@permission_classes([AllowAny]) 
def speak_realtime(request):
    text = request.data.get("text", "Hello, this is a real-time streaming test!")

    def stream_audio():
        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text
        ) as response:
            for chunk in response.iter_bytes(chunk_size=1024):
                yield chunk

    return StreamingHttpResponse(stream_audio(), content_type="audio/mpeg")

@csrf_exempt
def openai_transcription(request):
    if request.method == 'POST' and request.FILES.get('audio'):
        audio_file = request.FILES['audio']
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=(audio_file.name, audio_file.read(), audio_file.content_type),
        )
        print("Transcription result:", transcription.text)
        return JsonResponse({'transcription': transcription.text})
    else:
        return JsonResponse({'error': 'No audio file provided'}, status=400)
    
class QuizDetailView(generics.RetrieveAPIView):
    serializer_class = QuizDetailSerializer
    permission_classes = [IsAuthenticated]
    #permission_classes = [AllowAny]
    
    def get_queryset(self):
        return Quiz.objects.all().prefetch_related('video_segments')
    
class UnitListView(generics.ListAPIView):
    serializer_class = UnitWithQuizzesSerializer
    permission_classes = [IsAuthenticated]
    #permission_classes = [AllowAny]
    
    def get_queryset(self):
        category_id = self.kwargs.get('category_id')
        queryset = Unit.objects.filter(category_id=category_id).order_by('unit_number')
        #print("UnitListView, Filtered Units no Prefetch:", queryset)
        return queryset
   
@api_view(["GET"])
def get_question_by_number(request, quiz_id, question_number):
    #print("get_question_by_number called with quiz_id:", quiz_id, " question_number:", question_number)
    try:
        question = Question.objects.get(quiz_id=quiz_id, question_number=question_number)
        serializer = QuestionSerializer(question)
        return Response(serializer.data)
    except Question.DoesNotExist:
        return Response({
            "error": "Question not found for the given quiz_id and question_number."
        }, status=404)
    
    
@api_view(["POST"])
def get_question_by_number_live(request, quiz_id, question_number):
    #print("get_question_by_number called with quiz_id:", quiz_id, " question_number:", question_number)
    # request.data contains user_name, retrieve it
    user_name = request.data.get('user_name', 'anonymous')
    try:
        question = Question.objects.get(quiz_id=quiz_id, question_number=question_number)
        # use setting.R_CONN to publish a notification to Redis channel to notify clients 
        # a user has retrieved a question, and include the question number and user_name in the notification
        # predent user_name to the string "_live_question_number" 
        # and save to Redis store for bootstrap purpose when user first logs in during a live quiz session, so that the frontend can retrieve the latest live question number and display the correct question to the user when they log in or refresh the page during a live quiz session
       
        # key = f"{user_name}_live_question_number"
        # settings.R_CONN.set(key, question_number)
        
        # nofity clients (users) via Redis channel
        
        settings.R_CONN.publish('notifications', json.dumps({
            "message_type": "live_question_retrieved",
            "content": question.question_number,
            "user_name": user_name,
        }))
        
        serializer = QuestionSerializer(question)
        return Response(serializer.data)
    except Question.DoesNotExist:
        return Response({
            "error": "Question not found for the given quiz_id and question_number."
        }, status=404)
    
@api_view(["POST"])
def create_video_quiz_attempt(request):
        """
            Create a QuizAttempt for the given quiz and user (used only in TakeVideoQuiz)
        """
        quiz_id = request.data.get('quiz_id', None)
        number_of_questions_to_preload = request.data.get('number_of_questions_to_preload', 3)
        
        quiz_attempt  = QuizAttempt.objects.create(
            user_name=request.data['user_name'],
            quiz_id=quiz_id,
            completion_status="uncompleted",
            
        )
        #print("***** New QuizAttempt created.")
        # print("***** New QuizAttempt created for quiz_id", pk, "and user_name", request.data['user_name'])
        serializer = QuizAttemptSerializer(quiz_attempt)
    
        loaded_questions = Question.objects.filter(quiz_id=quiz_id).order_by('question_number')[:number_of_questions_to_preload]
        # if loaded_questions:
            # print("Loaded questions size for quiz_id", pk, ":", loaded_questions.count())
            # only create question attempts for the first question in the quiz, and create the next question attempt when the user clicks "Next" button in the frontend after they answer the first question, to avoid creating too many question attempts at once and overwhelming the frontend with too much data, which can cause performance issues in React Native.
            # create question attempt for the first question of loaded questions
        return Response({
            "quiz_attempt": serializer.data,
            "created": True,
            "questions": QuestionSerializer(loaded_questions, many=True).data if loaded_questions.exists() else None,
            "question_attempt_id": None,
            })
            
          
@api_view(["GET"])
def get_video_segment_questions(request, pk):
    # pk is the video_segment_id from the URL
    questions = Question.objects.filter(video_segment_id=pk).order_by('question_number')
    return Response({
        "questions": QuestionSerializer(questions, many=True).data
    })

              
"""
  
    def post(self, request, *args, **kwargs):
        print(" ******* QuestionPartialListView called.........")
        pk = self.kwargs.get('pk')
        starting_question_number = self.kwargs.get('starting_question_number')
        print("QuestionRangeListView, starting_question_number:", starting_question_number)
        number_of_questions = self.kwargs.get('number_of_questions')
        print("QuestionRangeListView, number_of_questions:", number_of_questions)
        
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

"""
              
"""      
api_view(["POST"])
def create_video_quiz_attempt(request):
   
        quiz_id = request.data.get('quiz_id', None)
        
        quiz_attempt  = QuizAttempt.objects.create(
            user_name=request.data['user_name'],
            quiz_id=quiz_id,
            completion_status="uncompleted",
            
        )
            #print("***** New QuizAttempt created.")
        serializer = QuizAttemptSerializer(quiz_attempt)
            #print(" QQQQQQQQQQQ QuizAttempt created:", serializer.data)
        return Response({
                "quiz_attempt": serializer.data,
                "created": True,
            })
"""           
                    
"""
@api_view(["POST"])
def get_or_create_quiz_attempt(request, pk):
        # get number_of_questions_to_preload from request.data, default to 3
        number_of_questions_to_preload = request.data.get('number_of_questions_to_preload', 3)
        #print("***** get_or_create_quiz_attempt_react_native called. Number of questions preloaded:", number_of_questions_to_preload)
        #print(" user name", request.data['user_name'])
        #print(" quiz id", pk)  
        quiz_attempt, created  = QuizAttempt.objects.get_or_create(
            user_name=request.data['user_name'],
            quiz_id=pk,
            completion_status="uncompleted",
            defaults={'score': 0, 'user_name': request.data['user_name'], 'quiz_id' : pk, "completion_status":"uncompleted"}
        )
        if created:
            # print("***** New QuizAttempt created for quiz_id", pk, "and user_name", request.data['user_name'])
            serializer = QuizAttemptSerializer(quiz_attempt)
    
            loaded_questions = Question.objects.filter(quiz_id=pk).order_by('question_number')[:number_of_questions_to_preload]
            if loaded_questions:
                # print("Loaded questions size for quiz_id", pk, ":", loaded_questions.count())
                # only create question attempts for the first question in the quiz, and create the next question attempt when the user clicks "Next" button in the frontend after they answer the first question, to avoid creating too many question attempts at once and overwhelming the frontend with too much data, which can cause performance issues in React Native.
              
                first_question = loaded_questions[0]
                # create question attempt for the first question of loaded questions
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": True,
                    "questions": QuestionSerializer(loaded_questions, many=True).data,
                    "question_attempt_id": None,
                    "question_attempt_number": 1,
                })
            else:
                # no questions in the quiz
                print("No questions found in the quiz.")
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": True,
                    "questions": None,
                    "question_attempt_id": None,
                })                
        else:
            #print("^^^^^^^^^^^^^^^^^^^^^^^ QuizAttempt already exists.")
            serializer = QuizAttemptSerializer(quiz_attempt)
            last_question_attempt = quiz_attempt.question_attempts.order_by('-id').first()   
            #print(" ^^^^^^^^^^^^^^^^^^^^^^ Last completed question attempt id:", last_question_attempt.id if last_question_attempt else "None", " question id:", last_question_attempt.question.id if last_question_attempt else "None", " completed:", last_question_attempt.completed if last_question_attempt else "None")         
            # check if last question attempt is completed
            if last_question_attempt and not last_question_attempt.completed:
                pending_question = last_question_attempt.question
                pending_question_number = pending_question.question_number
                    # also retrieve the next 2 questions after the pending question,
                    # using the question_number of the pending question,
                questions = Question.objects.filter(quiz_id=pk, question_number__gte=pending_question_number).order_by('question_number')[:3]
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": False,
                    "questions": QuestionSerializer(questions, many=True).data,
                    "question_attempt_id": last_question_attempt.id,
                })
            else:
                # if last question attempt was completed, grab the next 3 questions after the last completed question, using the question_number of the last completed question, and create a question attempt for the first question among the next 3 questions
                if (last_question_attempt is None):
                    # no attempt yet, treat like a new quiz attempt
                    questions = Question.objects.filter(quiz_id=pk).order_by('question_number')[:number_of_questions_to_preload]
                    return Response({
                        "quiz_attempt": serializer.data,
                        "created": False,
                        "questions": QuestionSerializer(questions, many=True).data,
                        "question_attempt_id": None,
                    })
                else:
                    last_question_completed = last_question_attempt.question
                    #last_question_completed_question_number = last_question_completed.question_number
                    # grab the next 3 questions after the last completed question
                    questions = Question.objects.filter(quiz_id=pk, question_number__gt=last_question_completed.question_number).order_by('question_number')[:3]
                    next_question = Question.objects.filter(quiz_id=pk, question_number__gt=last_question_attempt.question.question_number).order_by('question_number').first()
                    if next_question:
                        question_attempt = QuestionAttempt.objects.create(
                            quiz_attempt=quiz_attempt,
                            question=next_question,
                            completed=False,
                        )
                        #print("Created next QuestionAttempt for Question id:", next_question.id, "question_attempt id:", question_attempt.id)
                        return Response({
                            "quiz_attempt": serializer.data,
                            "created": False,
                            "questions": QuestionSerializer(questions, many=True).data,
                            "question_attempt_id": question_attempt.id,
                        })
                    else:
                        # no more questions available
                        #print("No more questions available in the quiz.")
                        return Response({
                            "quiz_attempt": serializer.data,
                            "created": False,
                            "questions": None,
                            "question_attempt_id": None,
                        })
                  
"""

@api_view(["POST"])
def get_or_create_quiz_attempt(request, pk):
        """
            Create or retrieve a QuizAttempt for the given quiz and user.
        """
        # print("********** get_or_create_quiz_attempt called.................")
        # get number_of_questions_to_preload from request.data, default to 3
        number_of_questions_to_preload = request.data.get('number_of_questions_to_preload', 3)
        #print("***** get_or_create_quiz_attempt_react_native called. Number of questions preloaded:", number_of_questions_to_preload)
        #print(" user name", request.data['user_name'])
        #print(" quiz id", pk)  
        quiz_attempt, created  = QuizAttempt.objects.get_or_create(
            user_name=request.data['user_name'],
            quiz_id=pk,
            completion_status="uncompleted",
            defaults={'score': 0, 'user_name': request.data['user_name'], 'quiz_id' : pk, "completion_status":"uncompleted"}
        )
        if created:
            # print("***** New QuizAttempt created for quiz_id", pk, "and user_name", request.data['user_name'])
            serializer = QuizAttemptSerializer(quiz_attempt)
    
            #loaded_questions = Question.objects.filter(quiz_id=pk).order_by('question_number')[:number_of_questions_to_preload]
            # retrieve the first question of the quiz, using question_number=1, to ensure the question attempt created is always for the first question of the quiz, 
            first_question = Question.objects.filter(quiz_id=pk, question_number=1).first()
            # print("First question retrieved for quiz_id", pk, ":", first_question)
            if first_question:
                # print("Loaded questions size for quiz_id", pk, ":", loaded_questions.count())
                # only create question attempts for the first question in the quiz, and create the next question attempt when the user clicks "Next" button in the frontend after they answer the first question, to avoid creating too many question attempts at once and overwhelming the frontend with too much data, which can cause performance issues in React Native.
                # create question attempt for the first question of loaded questions
                question_attempt = QuestionAttempt.objects.create(
                    quiz_attempt=quiz_attempt,
                    question_attempt_number=1,
                    question=first_question,
                    completed=False,
                )
                return Response({
                    "created": True,
                    "quiz_attempt": serializer.data,
                    "question": QuestionSerializer(first_question).data,
                    "question_attempt_id": question_attempt.id,
                })
            else:
                # no questions in the quiz
                # print("No questions found in the quiz.")
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": True,
                    "question": None,
                    "question_attempt_id": None,
                })                
        else:
            # print("^^^^^^^^^^^^^^^^^^^^^^^ QuizAttempt already exists.")
            serializer = QuizAttemptSerializer(quiz_attempt)
            last_question_attempt = quiz_attempt.question_attempts.order_by('-id').first()   
            #print(" ^^^^^^^^^^^^^^^^^^^^^^ Last completed question attempt id:", last_question_attempt.id if last_question_attempt else "None", " question id:", last_question_attempt.question.id if last_question_attempt else "None", " completed:", last_question_attempt.completed if last_question_attempt else "None")         
            # check if last question attempt is completed
            if last_question_attempt and not last_question_attempt.completed:
                # print("Last question attempt is not completed, last question attempt id = ", last_question_attempt.id , " pending question id:", last_question_attempt.question.id)
                pending_question = last_question_attempt.question
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": False,
                    "question": QuestionSerializer(pending_question).data,
                    "question_attempt_id": last_question_attempt.id,
                })
            elif last_question_attempt and last_question_attempt.completed:
                # print("Last question attempt is completed, last completed question id:", last_question_attempt.question.id)
                # if last question attempt was completed, grab the next question after the last completed question, using the question_number of the last completed question, and create a question attempt for the next question
                last_question_completed = last_question_attempt.question
                next_question = Question.objects.filter(quiz_id=pk, question_number__gt=last_question_completed.question_number).order_by('question_number').first()
                if next_question:
                    question_attempt = QuestionAttempt.objects.create(
                        quiz_attempt=quiz_attempt,
                        question=next_question,
                        completed=False,
                    )
                    # print("Created next QuestionAttempt for Question id:", next_question.id, "question_attempt id:", question_attempt.id)
                    return Response({
                        "quiz_attempt": serializer.data,
                        "created": False,
                        "question": QuestionSerializer(next_question).data,
                        "question_attempt": QuestionAttemptSerializer(question_attempt).data,
                    })
            else:       
                # should not be here, send a error message back
                print("Error: No question attempts found for this quiz attempt, which should not happen. QuizAttempt id:", quiz_attempt.id)
                return Response({
                    "error": "No question attempts found for this quiz attempt, which should not happen."
                }, status=500)
                  

from django.core import serializers
                    
@api_view(["POST"])
def get_or_create_quiz_attempt_react_native(request, pk):
        """
            Create or retrieve a QuizAttempt for the given quiz and user.
        """
        # get number_of_questions_to_preload from request.data, default to 3
        number_of_questions_to_preload = request.data.get('number_of_questions_to_preload', 3)
        # print("***** get_or_create_quiz_attempt_react_native called. Number of questions preloaded:", number_of_questions_to_preload)
        quiz_attempt, created  = QuizAttempt.objects.get_or_create(
            user_name=request.data['user_name'],
            quiz_id=pk,
            completion_status="uncompleted",
            defaults={'score': 0, 'user_name': request.data['user_name'], 'quiz_id' : pk}
        )
        if created:
            serializer = QuizAttemptSerializer(quiz_attempt)
    
            loaded_questions = Question.objects.filter(quiz_id=pk).order_by('question_number')[:number_of_questions_to_preload]
            if loaded_questions:
                # print("Loaded questions size for quiz_id", pk, ":", loaded_questions.count())
                # only create question attempts for the first question in the quiz, and create the next question attempt when the user clicks "Next" button in the frontend after they answer the first question, to avoid creating too many question attempts at once and overwhelming the frontend with too much data, which can cause performance issues in React Native.
                # print(serializers.serialize('json', loaded_questions))
  
                #for q in loaded_questions:
                #    print(vars(q))
                first_question = loaded_questions[0]
                # create question attempt for the first question of loaded questions
                question_attempt = QuestionAttempt.objects.create(
                    quiz_attempt=quiz_attempt,
                    question_attempt_number=1,
                    question=first_question,
                    completed=False,
                )
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": True,
                    "questions": QuestionSerializer(loaded_questions, many=True).data,
                    "question_attempt_id": question_attempt.id,
                    "question_attempt_number": 1,
                })
            else:
                # no questions in the quiz
                print("No questions found in the quiz.")
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": True,
                    "questions": None,
                    "question_attempt_id": None,
                })
                    
        else:
            # print("^^^^^^^^^^^^^^^^^^^^^^^ QuizAttempt already exists.")
            serializer = QuizAttemptSerializer(quiz_attempt)
            last_question_attempt = quiz_attempt.question_attempts.order_by('-id').first()   
            # print(" ^^^^^^^^^^^^^^^^^^^^^^ Last completed question attempt id:", last_question_attempt.id if last_question_attempt else "None", " question id:", last_question_attempt.question.id if last_question_attempt else "None", " completed:", last_question_attempt.completed if last_question_attempt else "None")         
            # check if last question attempt is completed
            if last_question_attempt and not last_question_attempt.completed:
                pending_question = last_question_attempt.question
                pending_question_number = pending_question.question_number
                    # also retrieve the next 2 questions after the pending question,
                    # using the question_number of the pending question,
                questions = Question.objects.filter(quiz_id=pk, question_number__gte=pending_question_number).order_by('question_number')[:3]
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": False,
                    "questions": QuestionSerializer(questions, many=True).data,
                    "question_attempt_id": last_question_attempt.id,
                })
            else:
                # if last question attempt was completed, grab the next 3 questions after the last completed question, using the question_number of the last completed question, and create a question attempt for the first question among the next 3 questions
                last_question_completed = last_question_attempt.question
                #last_question_completed_question_number = last_question_completed.question_number
                # grab the next 3 questions after the last completed question
                questions = Question.objects.filter(quiz_id=pk, question_number__gt=last_question_completed.question_number).order_by('question_number')[:3]
                next_question = Question.objects.filter(quiz_id=pk, question_number__gt=last_question_attempt.question.question_number).order_by('question_number').first()
                if next_question:
                    question_attempt = QuestionAttempt.objects.create(
                        quiz_attempt=quiz_attempt,
                        question=next_question,
                        completed=False,
                    )
                    #print("Created next QuestionAttempt for Question id:", next_question.id, "question_attempt id:", question_attempt.id)
                    return Response({
                        "quiz_attempt": serializer.data,
                        "created": False,
                        "questions": QuestionSerializer(questions, many=True).data,
                        "question_attempt_id": question_attempt.id,
                    })
                else:
                    # no more questions available
                    #print("No more questions available in the quiz.")
                    return Response({
                        "quiz_attempt": serializer.data,
                        "created": False,
                        "questions": None,
                        "question_attempt_id": None,
                    })
                    
        
@api_view(["GET"])
def continue_quiz_attempt(request, pk):
    try:
        quiz_attempt = QuizAttempt.objects.get(id=pk)
        #print("Continuing QuizAttempt id:", pk)
        #make a new QuestionAttempt for the first question in the quiz
        # inspect the last question attempt of this quiz attempt
        last_question_attempt = quiz_attempt.question_attempts.order_by('-id').first()
        if last_question_attempt:
        # check if last question attempt is completed
            if last_question_attempt.completed:
                #print("Last QuestionAttempt is completed. Creating next QuestionAttempt.")
                next_question = Question.objects.filter(quiz_id=quiz_attempt.quiz_id, question_number__gt=last_question_attempt.question.question_number).order_by('question_number').first()
                if next_question:
                    #print("Next question found: question id = ", next_question.id)
                    question_attempt = QuestionAttempt.objects.create(
                        quiz_attempt=quiz_attempt,
                        question=next_question,
                        completed=False,
                        
                    )
                    question_serializer = QuestionSerializer(next_question)
                    return Response({
                        "message": "Next QuestionAttempt created.",
                        "quiz_attempt_id": pk,
                        "question": question_serializer.data,
                        "question_attempt_id": question_attempt.id
                    })
                else:
                    print("No more questions available in the quiz.")
                    return Response({
                        "message": "No more questions available in the quiz.",
                        "quiz_attempt_id": pk,
                        "question": None
                    })
            else:
                # print("Last QuestionAttempt is not completed. Returning the same question.")
                question_serializer = QuestionSerializer(last_question_attempt.question)
                return Response({
                    "message": "Returning the current QuestionAttempt.",
                    "quiz_attempt_id": pk,
                    "question_attempt_id": last_question_attempt.id,
                    "question": question_serializer.data
                }) 
    
    
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
        
@api_view(["GET"])
def start_live_quiz(request, pk):
    try:
        quiz = Quiz.objects.get(id=pk)
        # send a notification to Redis channel to notify clients 
        settings.R_CONN.publish('notifications', json.dumps({
            "message_type": "live_quiz_id",
            "content": pk,
            "quiz_name": quiz.name,
        }))
        
        # use R_CONN from settings.py to persist live quiz id to Redis store
        # (for recovery purposes in case in case user drops connection and reconnects later
        # or is logged in during a live quiz session)
        # print("Persisting live quiz id to Redis store with key 'live_quiz_id' and value:", pk)
        settings.R_CONN.set('live_quiz_id', pk)
        # settings.R call('JSON.SET', `user:${user_name}`, '$', JSON.stringify(newUser));
        # settings.R_CONN.call('JSON.SET', "user:student1", '$', json.dumps(pk))
        
        return Response({
            "message": "Live quiz started and notification sent.",
            "quiz_id": pk,
            "quiz_name": quiz.name,
        })
        
    except Quiz.DoesNotExist:
        #print(" ******* Live quiz with id", pk, " not found.")
        return Response({
            "error": " *** Quiz with id" + str(pk) + " not found."
        }, status=404)
   
@api_view(["POST"])
def send_live_question_number(request, pk):
    # pk is question_number
    # body contains live_quiz_id id
    try:
      
        # print("send_live_question_number called with pk (question_number):", pk, " request.data:", request.data)
        # pik is the question_number
        live_quiz_id = request.data.get('live_quiz_id', None)
        target_user_name = request.data.get('target_user_name', 'everybody')
        
        question_number = pk
        question = Question.objects.filter(quiz_id=live_quiz_id, question_number=pk).first()
        if question is None:
            #print(" ******* Question with quiz_id", live_quiz_id, " and question_number ", pk, " not found.")
            return Response({
                "error": "Question not found for the given question_number."
            }, status=404)
            
        # save key as "live_question_number" and value to Redis store using settings.R_CONN, 
        # so that the frontend can retrieve the latest live question number and retrieve it
        # when they log in or refresh the page during a live quiz session
        
        settings.R_CONN.set('live_question_number', question_number)
        
        # send a notification to Redis channel to notify clients
        settings.R_CONN.publish('notifications', json.dumps({
            "message_type": "live_question_number",
            "content": question_number,
            "target_user_name": target_user_name,
        }))
        # return a success response
        return Response({
            "status": "Live question number sent to notifications channel",
            "question_number": question_number,
        }, status=200)
        
    
    except Exception as e:
        return Response({
            "error": f"Error processing request: {str(e)}"
        }, status=500)
       
        
@api_view(["GET"])
def reset_quiz_attempt(request, pk):
    """
        Reset the quiz attempt by deleting existing question attempts
        and setting the quiz attempt status to uncompleted.
    """
    try:
        quiz_attempt = QuizAttempt.objects.get(id=pk)
        # Delete all associated question attempts
        #print("Resetting QuizAttempt id:", pk)
        quiz_attempt.question_attempts.all().delete()
        # Reset quiz attempt status
        quiz_attempt.completion_status = "uncompleted"
        quiz_attempt.score = 0
        quiz_attempt.save()
        
        #make a new QuestionAttempt for the first question in the quiz
        first_question = Question.objects.filter(quiz_id=quiz_attempt.quiz_id).order_by('question_number').first()
        if first_question:
            question_attempt = QuestionAttempt.objects.create(
                quiz_attempt=quiz_attempt,
                question=first_question,
                completed=False,
            )
        
        question_serializer = QuestionSerializer(first_question)
        return Response({
            "message": "Quiz attempt has been reset. A new QuestionAttempt has been created for the first question.",
            "quiz_attempt_id": pk,
            "question": question_serializer.data,
            "question_attempt_id": question_attempt.id
        })
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
            
            
        
@api_view(["POST"])
def mark_quiz_attempt_completed(request, pk):
    """
        Mark the quiz attempt completed by setting the quiz attempt status to completed.
    """
    try:
        quiz_attempt = QuizAttempt.objects.get(id=pk)
        # print("***** Marking QuizAttempt id:", pk, " as completed.")
        quiz_attempt.completion_status = "completed"
        quiz_attempt.save()
        return Response({
            "message": "Quiz attempt has been marked as completed.",
            "quiz_attempt_id": pk,
        })
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
        
@api_view(["GET"])
def set_review_mode(request, pk):
    """
        Mark the quiz attempt completed by setting the quiz attempt status to completed.
    """
    try:
        print("***** SETTING REVIEW MODE FOR QuizAttempt id:", pk)
        quiz_attempt = QuizAttempt.objects.get(id=pk)
       
        quiz_attempt.review_state = True
        quiz_attempt.save()
        return Response({
            "message": "Quiz attempt has been marked as completed.",
            "quiz_attempt_id": pk,
        })
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
            
            
# 
@api_view(["POST"])
def replenish_incorrect_questions(request, pk):
    """
        Get all incorrectly answered questions for a quiz attempt.
    """
    try:      
        # print(" ------->>>>>>>>> in replenish incorrect questions, request.data:", request.data)
        # read starting_question_attempt_number from body
        starting_question_attempt_number = request.data.get('starting_question_attempt_number', 1)
        # print("get_incorrect_questions called for quiz_attempt id:", pk, " starting_question_attempt_number:", starting_question_attempt_number)
        number_of_questions_to_load = request.data.get('number_of_questions_to_load', 1)
        # search for errorneous question attempts that have been corrected (using the corrected flag)
        # print("get_incorrect_questions called for quiz_attempt id:", pk, " starting_question_attempt_number:", starting_question_attempt_number)
        errorneous_question_attempts = QuestionAttempt.objects.filter(
            quiz_attempt_id=pk, 
            error_flag=True, 
            corrected=False,
            question_attempt_number__gte=starting_question_attempt_number
        )
    
        # for simplicity, retrieve only the first question attempt that is errorneous and not corrected, 
        # and return the question data for that question attempt, along with a flag indicating whether there are more incorrect questions to be replenished after this one (i.e. whether the count of errorneous_question_attempts is greater than 1)
        erroreous_attempts = errorneous_question_attempts.order_by('id')[:number_of_questions_to_load]
        #print("Errorneous question attempts to be replenished for quiz_attempt id:", pk, ":", erroreous_attempts)
        combined = [
        {
            "question": QuestionSerializer(attempt.question).data,
            "question_attempt_number": attempt.question_attempt_number,
            "question_attempt_id": attempt.id,
        }
        for attempt in erroreous_attempts
        ]
        
        return Response({
            "incorrect_questions": combined,
            "quiz_attempt_id": pk,
        })        
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
        
@api_view(["POST"])
def replenish_incorrect_questions_react_native(request, pk):
    """
        Get all incorrectly answered questions for a quiz attempt.
    """
    try:      
        # print(" ------->>>>>>>>> in replenish incorrect questions, request.data:", request.data)
        # read starting_question_attempt_number from body
        current_question_id = request.data.get('current_question_id', 1)
        # print("get_incorrect_questions called for quiz_attempt id:", pk, " starting_question_attempt_number:", starting_question_attempt_number)
        number_of_questions_to_load = request.data.get('number_of_questions_to_load', 1)
        # search for errorneous question attempts that have been corrected (using the corrected flag)
        # print("get_incorrect_questions called for quiz_attempt id:", pk, " starting_question_attempt_number:", starting_question_attempt_number)
        errorneous_question_attempts = QuestionAttempt.objects.filter(
            quiz_attempt_id=pk, 
            error_flag=True, 
            corrected=False,
            question_attempt_number__gte=1
        ).exclude(question_id=current_question_id)
    
        # for simplicity, retrieve only the first question attempt that is errorneous and not corrected, 
        # and return the question data for that question attempt, along with a flag indicating whether there are more incorrect questions to be replenished after this one (i.e. whether the count of errorneous_question_attempts is greater than 1)
        erroreous_attempts = errorneous_question_attempts.order_by('id')[:number_of_questions_to_load]
        #print("Errorneous question attempts to be replenished for quiz_attempt id:", pk, ":", erroreous_attempts)
        combined = [
        {
            "question": QuestionSerializer(attempt.question).data,
            "question_attempt_number": attempt.question_attempt_number,
            "question_attempt_id": attempt.id,
        }
        for attempt in erroreous_attempts
        ]
        
        return Response({
            "incorrect_questions": combined,
            "quiz_attempt_id": pk,
        })        
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
        
@api_view(["GET"])
def get_next_incorrect_question_attempt(request, pk):
    try:
        quiz_attempt = QuizAttempt.objects.get(id=pk)
        # find the next question attempt that was wrong
        # if user has made several wrong attempts on the same question,
        # we only select the latest (which is marked stale = True) 
    
        incorrect_attempt = quiz_attempt.question_attempts.filter(
            error_flag=True, 
            corrected=False,
            stale=False).order_by('question_attempt_number').first()
        
        # update incorrect_attempt as "stale" (ruled out for review) since we are doing another attempt
        # for the same question.
  
        if incorrect_attempt:
            
            incorrect_attempt.stale = True
            incorrect_attempt.save()
        
            last_question_attempt_number = incorrect_attempt.quiz_attempt.question_attempts.order_by('question_attempt_number').last().question_attempt_number
            new_question_attempt = QuestionAttempt.objects.create(
                quiz_attempt_id=pk,
                question=incorrect_attempt.question,
                question_attempt_number=last_question_attempt_number + 1,
                review_state=True,
                stale = False,  
                completed=False,
            )
            return Response({
                "quiz_attempt_id": pk,
                "question": QuestionSerializer(incorrect_attempt.question).data,
                "question_attempt_id": new_question_attempt.id,
            })
       
        else:
            return Response({
                "message": "No more incorrect questions to replenish.",
                "quiz_attempt_id": pk,
            })

    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404) 
        
@api_view(["POST"])
def get_incorrect_questions(request, pk):
    """
        Get all incorrectly answered questions for a quiz attempt.
        This view is called only ONCE on the client side after all questions in normal mode
        have been exhausted, 
        
    """
    try:      
        # read starting_question_attempt_number from body
        # KPHAM: currently, starting_question_attempt_number is set to 1 on client (react native)
        starting_question_attempt_number = request.data.get('starting_question_attempt_number', 1)
        number_of_questions_to_load = request.data.get('number_of_questions_to_load', 2)
        # search for errorneous question attempts that have been corrected (using the corrected flag)
        # print("*********** get_incorrect_questions,  number of questions to load ", number_of_questions_to_load, " for quiz_attempt id:", pk, " starting_question_attempt_number:", starting_question_attempt_number)
        errorneous_question_attempts = QuestionAttempt.objects.filter(
            quiz_attempt_id=pk, 
            error_flag=True, 
            corrected=False,
            question_attempt_number__gte=starting_question_attempt_number
        )
    
        erroreous_attempts = errorneous_question_attempts.order_by('id')[:number_of_questions_to_load]
        
        # has_more_incorrect = errorneous_question_attempts.count() > 3
        
        combined = [
        {
            "question": QuestionSerializer(attempt.question).data,
            "question_attempt_number": attempt.question_attempt_number,
            "question_attempt_id": attempt.id,
        }
        for attempt in erroreous_attempts
        ]
        
        return Response({
            "incorrect_questions": combined,
            "quiz_attempt_id": pk,
        })        
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
   
@api_view(["POST"])
def create_question_attempt(request, pk):
    # pk is quiz_attempt_id
    # body contain question id
    # get body data
    try:
  
        # retrieve flag review_state from the request body
        review_state_from_request = request.data.get('review_state', 'normal')  # default to 'normal' if not provided
        quiz_attempt = QuizAttempt.objects.get(id=pk)
        if review_state_from_request == True or review_state_from_request == "review":
            quiz_attempt.review_state = True
            quiz_attempt.save()
            # print("QuizAttempt id:", pk, "marked as review state due to question attempt creation with review state.")
            
        question_id = request.data.get('question_id', None)
        #print("create_question_attempt for quiz_attempt id:", pk, " question_id:", question_id)
        if question_id is None:
            return Response({
                "error": "question_id is required in the request data."
            }, status=400)
        
        question = Question.objects.get(id=question_id)
        if question is None:
            return Response({
                "error": "Question not found for the given question_id."
            }, status=404)
   
        last_question_attempt = quiz_attempt.question_attempts.order_by('question_attempt_number').last()
        last_question_attempt_number = last_question_attempt.question_attempt_number if last_question_attempt else 0
        # print("$$$$$$$ Last question attempt number:", last_question_attempt_number)
        question_attempt = QuestionAttempt.objects.create(
            quiz_attempt=quiz_attempt,
            question=question,
            question_attempt_number=last_question_attempt_number + 1,
            completed=False,
            review_state = quiz_attempt.review_state,  # set the question attempt's review_state the same as the quiz attempt's review_state, so that the frontend can display the question attempt in review mode if the quiz attempt is in review mode.
            
        )
               
        # retrieve review_state from quiz_attempt
 
        # question_serializer = QuestionSerializer(question)
        return Response({
            "quiz_attempt_id": pk,
            "question_attempt_id": question_attempt.id,
            "question_attempt_number": question_attempt.question_attempt_number,
        })
        
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
        
        
@api_view(["POST"])
def create_next_question_attempt(request, pk):
    # pk is quiz_attempt_id
    # body contain current question number
    try:
         # retrieve current question number from request body
        current_question_number = request.data.get('current_question_number', None)
        
        quiz_attempt = QuizAttempt.objects.get(id=pk)
        review_state = quiz_attempt.review_state  # get the review_state of the quiz attempt
  
        # retrieve quiz for quiz_attempt.quiz_id
        quiz = Quiz.objects.get(id=quiz_attempt.quiz_id)
        # next_question_number is current_question_number + 1
        next_question_number = current_question_number + 1
        # retrieve the next question using quiz_id and next_question_number
        next_question = Question.objects.filter(quiz_id=quiz.id, question_number=next_question_number).first()
    
        if next_question is None:
            # see if there are any more incorrect question attempts 
            # if so, also return the number  incorrect question attempts
            number_incorrect_attempts = QuestionAttempt.objects.filter(
                quiz_attempt_id=pk,
                error_flag=True,
                corrected=False,
            ).count()
            
            # print("NO MORE QUESTIONS TO LOAD, next_question is None:", next_question is None)
            return Response({
                    "next_question_attempt": None,
                    "next_question": None,
                    "number_of_incorrect_attempts": number_incorrect_attempts,
            })
        
        last_question_attempt = quiz_attempt.question_attempts.order_by('question_attempt_number').last()
        last_question_attempt_number = last_question_attempt.question_attempt_number if last_question_attempt else 0
        question_attempt = QuestionAttempt.objects.create(
            quiz_attempt=quiz_attempt,
            question=next_question,
            question_attempt_number=last_question_attempt_number + 1,
            completed=False,
            review_state = review_state, 
        )
        return Response({
            "next_question_attempt": QuestionAttemptSerializer(question_attempt).data,
            "next_question": QuestionSerializer(next_question).data,
        })
        
        
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
        
        
        
@api_view(["POST"])
def process_live_question_attempt(request):
    try: 
        #print("process_question_attempt quiz attempt id", pk, " request.data:", request.data)
        user_answer = request.data.get('user_answer', '')
        assessment_results =  check_answer(request.data.get('format', ''), user_answer, request.data.get('answer_key', ''))
        #print(" type of assessment_results:", type(assessment_results))
        
        """
        assessment_results: {'error_flag': False, 'score': 5, 
        'cloze_question_results': [{'user_answer': 'am', 'answer_key': 'am', 'error_flag': False, 'score': 5}]}
        """
        # type of assessment_results: <class 'dict'>
        # assessment_results is a dictionary
        # let's access the score key of the dictionary
        score = assessment_results.get('score', 0)
        
        #print(" ****** process_live_question_attempt, assessment_results:", assessment_results)
        #print(" score to be published live:", assessment_results.score)
        """
         {'error_flag': False, 'score': 10, 
         'cloze_question_results': [{'user_answer': 'have', 'answer_key': 'have', 'error_flag': False, 'score': 5}, {'user_answer': 'seen', 'answer_key': 'seen', 'error_flag': False, 'score': 5}]}
        """
        from_user = request.data.get('user_name', 'anonymous')
        #print(" Publishing live score for user:", from_user)
      
        """
          message_type: 'live_score',
          content: value,  // format of content is "question_number: score", e.g. "1:5"
          user_name: name, // sender
         
        """
        # execute_command is a RedisJSON command to get the user document from Redis store, and access the live_total_score field in the user document, if not exist, initialize it to 0, then add the current score to the live_total_score,
        live_total_score = settings.R_CONN.execute_command('JSON.GET', f"user:{from_user}", '$.live_total_score')
        #print(" ***** Retrieved live_total_score from Redis for user", from_user, ":", live_total_score)
        # live_total_score is an array


# Assuming live_total_score is returned as a JSON string, e.g., "[999]"
        if live_total_score:
        # Parse the JSON string into a Python list
            live_total_score_list = json.loads(live_total_score)
            #print("Parsed live_total_score as list:", live_total_score_list)
        # IMPORTANT: since we are using JSON.GET with a path, the result is always a list, 
        # even if there is only one element in the list. 
        # So we need to extract the first element from the list to get the actual live_total_score value.
        # Extract the first (and only) element from the list
            live_total_score_int = int(live_total_score_list[0])
            #print("Parsed live_total_score as integer:", live_total_score_int)
        else:
            # If the value doesn't exist, initialize it to 0
            live_total_score_int = 0
            #print("live_total_score not found. Initialized to 0.")
            
        # compare live_total_score_int with 999
        if live_total_score_int >= 999:
            #print("live_total_score is greater than or equal to 999, resetting to 0.")
            live_total_score_int = 0
            
        # add current score to live_total_score_int
        live_total_score_int += score
        # update live_total_score in Redis store using settings.R_CONN.execute_command with RedisJSON command to update the live_total_score field in the user document in Redis store
        settings.R_CONN.execute_command('JSON.SET', f"user:{from_user}", '$.live_total_score', json.dumps(live_total_score_int))
        #print(" FINALLY live_total_score to be published for user", from_user, ":", live_total_score_int)
        score_data = {'message_type': 'live_score', 'content': {"score": score, "live_total_score": live_total_score_int , 'live_user_answer': user_answer }, 'user_name': from_user,}
        # notify other users via Redis channel 
        message = json.dumps(score_data)  # Convert entire data to JSON string because Redis only accepts strings, and we want to send a structured message that includes the score, live_total_score, and user_name, so we use a dictionary and convert it to a JSON string before sending it to Redis.
        # print("Publishing live score to Redis channel 'notifications':", message)
        settings.R_CONN.publish('notifications', message)
        
        return Response({
            "assessment_results": assessment_results,
        })
        
    except Exception as e:
        return Response({
            "error": f"Error processing answer: {str(e)}"
        }, status=500)

@api_view(["POST"])
def process_video_question_attempt(request, pk):
    #print("process_video_question_attempt called for question_attempt id:", pk, " request.data:", request.data)
    try: 
        # retrieve 
        active_segment_question_ids = request.data.get('active_segment_question_ids', [])
        #print(" active_segment_question_ids received in request data:", active_segment_question_ids)
        #print("process_question_attempt quiz attempt id", pk, " request.data:", request.data)
        assessment_results =  check_answer(request.data.get('format', ''), request.data.get('user_answer', ''), request.data.get('answer_key', ''))
        
        #print(" process_question_attempt, assessment_results:", assessment_results)
        error_flag = assessment_results.get('error_flag', True)
        
        score = 0 if error_flag else 5
        # request.data: {'user_answer': 'test answer', "answer_key": "correct answer"}
       
        question_attempt = QuestionAttempt.objects.get(id=pk)
        quiz_attempt = question_attempt.quiz_attempt
        
        # calculate score for quiz_attempt
        quiz_attempt.score = quiz_attempt.score + score
        
        # get next question
        next_question_number = question_attempt.question.question_number + 1
            #print(" Next question number FOUND (if not, then it's an error):", next_question_number)
            # get the question in database based on next_question_number and quiz_id
        next_question = Question.objects.filter(quiz_id=question_attempt.quiz_attempt.quiz_id, question_number=next_question_number).first()
        if not next_question:
            # end of quiz
            quiz_attempt.completion_status = "completed"
            quiz_attempt.save()
            return Response({
                    "assessment_results": assessment_results,
                    "quiz_attempt": { "completed": True, "score": quiz_attempt.score  }
            })
            
       
        # NOT END of quiz, if next_question.id doesn't belong to active_segment_question_ids then print out a warning
        if str(next_question.id) not in active_segment_question_ids:
            #print(" next question id doesn't belong to this segment. Return assessment results without next question id to client, and print a warning in the console.")
            return Response({
                    "assessment_results": assessment_results,
                    "quiz_attempt": { "completed": True, "score": quiz_attempt.score  }
                   
                })
        else:
            #print("next question belongs to segment, return results with next_questionId.....=", next_question.id, " returns it to client")
            return Response({
                    "assessment_results": assessment_results,
                    "quiz_attempt": { "completed": True, "score": quiz_attempt.score  },
                    "next_question_id": next_question.id
                })

    except QuestionAttempt.DoesNotExist:
        return Response({
            "error": "Question attempt not found."
        }, status=404)


@api_view(["POST"])
def process_timeout(request, pk):
    # print("process_timeout called for question_attempt id:", pk, " request.data:", request.data)
    try: 
        error_flag = True
        score = 0
        # question attempt for this question should have been created.
        # look for create_next_question_attempt in the frondend code (TakeQuiz.tsx)
        question_attempt = QuestionAttempt.objects.get(id=pk)
        
        question_attempt.error_flag = error_flag
        #print(" process_question_attempt, computed error_flag:", question_attempt.error_flag)
        question_attempt.score = score
        question_attempt.answer = "timeout"
        question_attempt.completed = True
        question_attempt.corrected = False
        question_attempt.save()
        
        return Response({
                "message": "Question attempt marked as timeout.",
                "question_attempt_id": pk,
        })
        
    
    except QuestionAttempt.DoesNotExist:
        return Response({
            "error": "Question attempt not found."
        }, status=404)


@api_view(["POST"])
def process_question_attempt(request, pk):
    try: 
        # print(" ***************** process_question_attempt quiz attempt id", pk, " request.data:", request.data)
        assessment_results =  check_answer(request.data.get('format', ''), request.data.get('user_answer', ''), request.data.get('answer_key', ''))
        #print(" ******* process_question_attempt, assessment_results:", assessment_results)
        #print(" process_question_attempt, assessment_results:", assessment_results)
        error_flag = assessment_results.get('error_flag', True)
               
        score = 0 if error_flag else 5
        
        corrected = False if error_flag else None  # if it's an error, then we set corrected to False. 
        
        # corrected = None if not error_flag else False  # if it's not an error, then we set corrected to None, meaning it doesn't matter, if it's an error, then we set corrected to False, meaning it's an errorneous attempt that has not been corrected yet.
     
        question_attempt = QuestionAttempt.objects.get(id=pk)
        
        question_attempt.error_flag = error_flag
        question_attempt.corrected = corrected
        #print(" process_question_attempt, computed error_flag:", question_attempt.error_flag)
        question_attempt.score = score
        question_attempt.answer = request.data.get('user_answer', '')
        question_attempt.completed = True
        question_attempt.save()
        
        # if no error, and in review state, search for the question attempt that has error_flag = True and 
        # corrected = False for the same question, mark it as corrected = True, so that it won't be counted as errorneous attempt
        # when we determine if quiz attempt has errors or not, 
        
        
        if (not error_flag) and question_attempt.quiz_attempt.review_state:
            #print(" This question attempt is correct, and quiz attempt is in review state, checking if there is an errorneous attempt for the same question to mark as corrected...")
            errorneous_attempts_for_same_question = QuestionAttempt.objects.filter(
                quiz_attempt=question_attempt.quiz_attempt,
                question=question_attempt.question,
                error_flag=True,
                corrected=False
            )
            if errorneous_attempts_for_same_question.exists():
                # print(" Found errorneous attempt(s) for the same question. id", question_attempt.question.id, "  Marking them as corrected.")
                errorneous_attempts_for_same_question.update(corrected=True)
            else:
                #print(" No errorneous attempts found for the same question.")
                pass
        
        
        quiz_attempt = question_attempt.quiz_attempt
        # calculate score for quiz_attempt
        quiz_attempt.score = quiz_attempt.score + score
                
        quiz_attempt.save()
        
        
        # use the corrected_flag to determine if a question attempt is an errorneous attempt 
        # that needs to be reviewed, or a redone attempt that has already been reviewed and corrected.
        return Response({
                "assessment_results": assessment_results,
                "quiz_attempt_score": { "score": quiz_attempt.score  }
        })
        
    except QuestionAttempt.DoesNotExist:
        return Response({
            "error": "Question attempt not found."
        }, status=404)


@api_view(["POST"])
def update_question_attempt(request, pk):
        try: 
            question_attempt = QuestionAttempt.objects.get(id=pk)
            print("update_question_attempt q attempt id", pk, " request.data:", request.data)
            
            # verify error_flag is present in request data
            if 'error_flag' not in request.data:
                return Response({
                    "error": "update_question_attempt: error_flag is required in the request data."
                }, status=400)
            
            question_attempt.error_flag = request.data.get('error_flag', question_attempt.error_flag)
            question_attempt.score = request.data.get('score', question_attempt.score)
            # question_attempt.answer = request.data.get('answer', question_attempt.answer)
            question_attempt.completed = True
            question_attempt.save()
            
            return Response({
                    "message": "Question attempt updated.",
                    "question_attempt_id": pk,
            })
            
            #print("Updated QuestionAttempt question number", question_attempt.question.question_number)
      
        except QuestionAttempt.DoesNotExist:
              return Response({
                "error": "Question attempt not found."
              }, status=404)


@api_view(["GET"])
def get_pending_assignments(request):
    pending = AssignmentStudent.objects.filter(
        user=request.user,
        status="pending"
    ).select_related('assignment__quiz')
    data = [
        {
            "assignment_id": a.assignment.id,
            "quiz_id": a.assignment.quiz.id,
            "quiz_name": a.assignment.quiz.name,
            "assigned_at": a.assigned_at,
        }
        for a in pending
    ]
    return Response({"pending_assignments": data})


