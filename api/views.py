from django.shortcuts import render

#from django.shortcuts import render
from django.contrib.auth.models import User
from rest_framework import generics
from api.serializers import UserSerializer, LevelWithCategoriesSerializer, \
     UnitWithQuizzesSerializer, QuizAttemptSerializer, QuizDetailSerializer
from english.serializers import QuestionSerializer 
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import Unit, Quiz, Question, QuizAttempt, QuestionAttempt, Level, VideoSegment
from rest_framework.decorators import api_view
from api.utils import check_answer

from django.conf import settings

#import redis

from rest_framework.response import Response

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
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
    print("send_notification endpoint hit request", request)
    try:
        # Parse the JSON payload (remember request.body is ALWAYS in JSON string format,
        # so you need to json.loads it to convert it to a Python dict before you can access its fields)
        print("send_notification called with request.body:", request.body)
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
    #print("level_list serializer.data:", serializer.data)
    return Response(serializer.data)
    
class QuizDetailView(generics.RetrieveAPIView):
    serializer_class = QuizDetailSerializer
    permission_classes = [IsAuthenticated]
    #permission_classes = [AllowAny]
    
    def get_queryset(self):
        return Quiz.objects.all().prefetch_related('video_segments')
    
class UnitListView(generics.ListAPIView):
    print("****** UnitListView called")
    serializer_class = UnitWithQuizzesSerializer
    permission_classes = [IsAuthenticated]
    #permission_classes = [AllowAny]
    
    def get_queryset(self):
        category_id = self.kwargs.get('category_id')
        queryset = Unit.objects.filter(category_id=category_id).order_by('unit_number')
        #print("UnitListView, Filtered Units no Prefetch:", queryset)
        print("****** UnitListView, SQL Query:", queryset.query)  # Debugging SQL query
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
       
        key = f"{user_name}_live_question_number"
        settings.R_CONN.set(key, question_number)
        
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
        
        print("create_quiz_attempt called with request.data:", request.data)
      
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
                    
@api_view(["POST"])
def get_or_create_quiz_attempt(request, pk):
        """
            Create or retrieve a QuizAttempt for the given quiz and user.
        """
    #sub_category_id = self.kwargs.get('pk')
        #units = Unit.objects.filter(sub_category_id=pk).order_by('unit_number')
        # retrieve user from request data (or use a default user for testing)
        #user = User.objects.get(username="admin")
        
        #print("get_or_create QuizAttempt for user id:", user.id, "and quiz_id:", pk)
        #print(" user is ", user)
        
        #print("request.data:", request.data)
        
        quiz_attempt, created  = QuizAttempt.objects.get_or_create(
            user_name=request.data['user_name'],
            quiz_id=pk,
            completion_status="uncompleted",
            defaults={'score': 0, 'user_name': request.data['user_name'], 'quiz_id' : pk}
        )
        if created:
            #print("***** New QuizAttempt created.")
            serializer = QuizAttemptSerializer(quiz_attempt)
            #print(" QQQQQQQQQQQ QuizAttempt created:", serializer.data)
            
            # also create the first QuestionAttempt for the first question in the quiz
            first_question = Question.objects.filter(quiz_id=pk).order_by('question_number').first()
            if first_question:
                question_attempt = QuestionAttempt.objects.create(
                    quiz_attempt=quiz_attempt,
                    question=first_question,
                    completed=False,
                )
                #print("Created first QuestionAttempt for Question id:", first_question.id, "question_attempt id:", question_attempt.id)
                
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": True,
                    "question": QuestionSerializer(first_question).data,
                    "question_attempt_id": question_attempt.id,
                })
            else: 
                # no questions in the quiz
                #print("No questions found in the quiz.")
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": True,
                    "question": None,
                    "question_attempt_id": None,
                })
                
        else:
            #print("^^^^^^ QuizAttempt already exists.")
            serializer = QuizAttemptSerializer(quiz_attempt)
            #retrieve all question_attempts for this quiz_attempt using one to many relationship
            #question_attempts = quiz_attempt.question_attempts.all()
            #get the last question attempt of the quiz_attempt
            last_question_attempt = quiz_attempt.question_attempts.order_by('-id').first()            
            # check if last question attempt is completed
            if last_question_attempt and not last_question_attempt.completed:
                # if not completed, return the same question
                #print("Returning incomplete last_question_attempt with  ")
                return Response({
                    "quiz_attempt": serializer.data,
                    "created": False,
                    "question": QuestionSerializer(last_question_attempt.question).data,
                    "question_attempt_id": last_question_attempt.id,
                })
            else:
                # if completed, create the next question attempt
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
                        "question": QuestionSerializer(next_question).data,
                        "question_attempt_id": question_attempt.id,
                    })
                else:
                    # no more questions available
                    #print("No more questions available in the quiz.")
                    return Response({
                        "quiz_attempt": serializer.data,
                        "created": False,
                        "question": None,
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
                print("Last QuestionAttempt is completed. Creating next QuestionAttempt.")
                next_question = Question.objects.filter(quiz_id=quiz_attempt.quiz_id, question_number__gt=last_question_attempt.question.question_number).order_by('question_number').first()
                if next_question:
                    print("Next question found: question id = ", next_question.id)
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
                print("Last QuestionAttempt is not completed. Returning the same question.")
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
        question_number = pk
        question = Question.objects.filter(quiz_id=live_quiz_id, question_number=pk).first()
        if question is None:
            print(" ******* Question with quiz_id", live_quiz_id, " and question_number ", pk, " not found.")
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
def create_question_attempt(request, pk):
    # pk is quiz_attempt_id
    # body contain question id
    # get body data
    try:
        #print("create_question_attempt called for quiz_attempt id:", pk, " request.data:", request.data)
        quiz_attempt = QuizAttempt.objects.get(id=pk)
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
        question_attempt = QuestionAttempt.objects.create(
            quiz_attempt=quiz_attempt,
            question=question,
            completed=False,
        )
        #print("Created QuestionAttempt is :", question_attempt.id, "for Question id:", question.id)
        question_serializer = QuestionSerializer(question)
        return Response({
            "quiz_attempt_id": pk,
            "question": question_serializer.data,
            "question_attempt_id": question_attempt.id
        })
        
    except QuizAttempt.DoesNotExist:
        return Response({
            "error": "Quiz attempt not found."
        }, status=404)
        
        
@api_view(["POST"])
def process_live_question_attempt(request):
    try: 
        #print("process_question_attempt quiz attempt id", pk, " request.data:", request.data)
        assessment_results =  check_answer(request.data.get('format', ''), request.data.get('user_answer', ''), request.data.get('answer_key', ''))
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
        
        # delete the live question number for the user from Redis store after processing the answer,
        #
        
        score_data = {'message_type': 'live_score', 'content': score, 'user_name': from_user}
        message = json.dumps(score_data)  # Convert entire data to JSON string
        # print("Message to send:", message)
        # notify other users via Redis channel 
        # print("Publishing live score to Redis channel 'notifications':", message)
        settings.R_CONN.publish('notifications', message)
        # settings.R_CONN.publish('notifications',json.dumps(testJson))
        
  
        #return JsonResponse({'status': 'Message sent to notifications channel'})
        
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
def process_question_attempt(request, pk):
    try: 
        #print("process_question_attempt quiz attempt id", pk, " request.data:", request.data)
        assessment_results =  check_answer(request.data.get('format', ''), request.data.get('user_answer', ''), request.data.get('answer_key', ''))
        
        #print(" process_question_attempt, assessment_results:", assessment_results)
        error_flag = assessment_results.get('error_flag', True)
        
        score = 0 if error_flag else 5
        # question attempt for this question should have been created.
        # look for create_next_question_attempt in the frondend code (TakeQuiz.tsx)
        question_attempt = QuestionAttempt.objects.get(id=pk)
        
        question_attempt.error_flag = error_flag
        #print(" process_question_attempt, computed error_flag:", question_attempt.error_flag)
        question_attempt.score = score
        question_attempt.answer = request.data.get('user_answer', '')
        question_attempt.completed = True
        question_attempt.save()
        
       
        """
         
        test_data = {'score': 10, 'user_name': 'test_user'}
        message = json.dumps(test_data)  # Convert entire data to JSON string
        print("Message to send:", message)
        settings.R_CONN.publish('notifications', message)
        """
        quiz_attempt = question_attempt.quiz_attempt
        # calculate score for quiz_attempt
        quiz_attempt.score = quiz_attempt.score + score
      
        if error_flag:
            # add question id to errorneous_questions in quiz_attempt
            #print(" **** question is errorneous, adding to errorneous_questions array")
            if (len(quiz_attempt.errorneous_questions) == 0) :
                #print("  errorneous_questions is empty, adding  question id")
                quiz_attempt.errorneous_questions = str(question_attempt.question.id)
            else:
                ##print("  errorneous_questions is not empty, adding question id")
                quiz_attempt.errorneous_questions += f",{question_attempt.question.id}"
                
            #quiz_attempt.save()
        else :  # remove question id from errorneous_questions in quiz_attempt if present
            #print(" **** question is correct, remove from errorneous_questions array if present")
            if quiz_attempt.errorneous_questions:
                errorneous_questions_array = quiz_attempt.errorneous_questions.split(",")
                if str(question_attempt.question.id) in errorneous_questions_array:
                    #print(" Removing question id:(correct results)", question_attempt.question.id, " from errorneous_questions_array")
                    errorneous_questions_array.remove(str(question_attempt.question.id))
                    quiz_attempt.errorneous_questions = ",".join(errorneous_questions_array)
                    #quiz_attempt.save()
                    
            #print(" Errorneous questions after removal (if any):", quiz_attempt.errorneous_questions)
            #print(" right now, quiz_attempt.errorneous_questions should have been updated")
     
        quiz_attempt.save()
        
        #print(" Finished updating question attempt. Now determining next question...")
        #print(" check if the quiz attempt is in review state")
        if quiz_attempt.review_state:
            #print(" Quiz attempt is in review state. Get the first errorneous question in list if any")
            errorneous_question_ids = [int(qid) for qid in quiz_attempt.errorneous_questions.split(",") if qid.isdigit()]
            # get first id in the errorneous_question_ids list
            if errorneous_question_ids:    # check for not empty or not null
                next_errorneous_question = Question.objects.filter(id__in=errorneous_question_ids).order_by('question_number').first()
                if next_errorneous_question:
                    return Response({
                        "next_question_id" : next_errorneous_question.id,
                        "assessment_results": assessment_results,
                        "quiz_attempt": { "completed": False, "score": quiz_attempt.score  }
                    })
            else:
                #print(" No more errorneous questions to review. Marking quiz attempt as completed.")
                quiz_attempt.completion_status = "completed"
                quiz_attempt.save()
                return Response({
                    "assessment_results": assessment_results,
                    "quiz_attempt": { "completed": True, "score": quiz_attempt.score  }
                })
                    
        # once, you get here, it means quiz_attempt is not in review state  
                    
                    
                    
        #print(" Quiz attempt not in review state. Let's see if this question is the last question in the quiz...")
        
        is_last_question = False
        next_question_number = question_attempt.question.question_number + 1
        last_question_in_quiz = question_attempt.quiz_attempt.quiz.questions.order_by('-question_number').first()
        if (next_question_number > last_question_in_quiz.question_number):
            is_last_question = True
        
        if (is_last_question ):
            if (quiz_attempt.errorneous_questions is None) or (quiz_attempt.errorneous_questions == ""):
                # mark quiz attempt as completed
                #print(" Last question, and errorneous strng is empty, marking quiz attempt as completed...")
                quiz_attempt.completion_status = "completed"
                quiz_attempt.save()
                # not returning a next question means the quiz attempt is completed
                return Response({
                    "assessment_results": assessment_results,
                    "quiz_attempt": { "completed": True, "score" : quiz_attempt.score  }
                })
            else: # get a question id from errorneous list in quiz_attempt
                #print(" Last question of quiz, but there are errorneous questions to review, proceeding to review...")
                # mark the review_sate of quiz_attempt as True
                quiz_attempt.review_state = True
                quiz_attempt.save()
                
                #print("proceed to do the first errorneous question")
                errorneous_question_ids = [int(qid) for qid in quiz_attempt.errorneous_questions.split(",") if qid.isdigit()]
                # get first id in the errorneous_question_ids list
                if errorneous_question_ids:    # check for not empty or not null
                    next_errorneous_question = Question.objects.filter(id__in=errorneous_question_ids).order_by('question_number').first()
                    # remove errouneous question from the errorneous_question_ids list
    
                            
                    if next_errorneous_question:
                        if quiz_attempt.errorneous_questions:
                            errorneous_questions_array = quiz_attempt.errorneous_questions.split(",")
                            if str(next_errorneous_question.id) in errorneous_questions_array:
                                errorneous_questions_array.remove(str(next_errorneous_question.id))
                                quiz_attempt.errorneous_questions = ",".join(errorneous_questions_array)
                                quiz_attempt.save()
                                
                            return Response({
                                "next_question_id" : next_errorneous_question.id,
                                "assessment_results": assessment_results,
                                "quiz_attempt": { "completed": False, "score": quiz_attempt.score  }
                        })
        else:
            #print(" Not the last question. Proceeding")
            # increment question number to get next question in the quiz
            next_question_number = question_attempt.question.question_number + 1
            #print(" Next question number FOUND (if not, then it's an error):", next_question_number)
            # get the question in database based on next_question_number and quiz_id
            next_question = Question.objects.filter(quiz_id=question_attempt.quiz_attempt.quiz_id, question_number=next_question_number).first()
            if next_question:
                # return next question data
                #print(" Found next question id:", next_question.id)
                return Response({
                        "assessment_results": assessment_results,
                        "next_question_id" : next_question.id,
                        "quiz_attempt": { "completed": False, "score": quiz_attempt.score  }
                })
            else:
                #print("Finished question attempt. But there's an error retrieving next question.................")
                return Response({
                    "assessment_results": assessment_results,
    
                })    
            
    except QuestionAttempt.DoesNotExist:
        return Response({
            "error": "Question attempt not found."
        }, status=404)

@api_view(["POST"])
def update_question_attempt(request, pk):
       try: 
        question_attempt = QuestionAttempt.objects.get(id=pk)
        #print("Updating QuestionAttempt id:", pk)

        #print("update_question_attempt q attempt id", pk, " request.data:", request.data)
        
        # verify error_flag is present in request data
        if 'error_flag' not in request.data:
            return Response({
                "error": "update_question_attempt: error_flag is required in the request data."
            }, status=400)
        
        #update fields
        question_attempt.error_flag = request.data.get('error_flag', question_attempt.error_flag)
        question_attempt.score = request.data.get('score', question_attempt.score)
        question_attempt.answer = request.data.get('answer', question_attempt.answer)
        question_attempt.completed = True
        question_attempt.save()
        
        #print("Updated QuestionAttempt question number", question_attempt.question.question_number)
        
        if question_attempt.error_flag:
            # add question id to errorneous_questions in quiz_attempt
            #print("  question is errorneous, adding to errorneous_questions array")
            quiz_attempt = question_attempt.quiz_attempt
            if (len(quiz_attempt.errorneous_questions) == 0) :
                #print("  errorneous_questions is empty, adding  question id")
                quiz_attempt.errorneous_questions = str(question_attempt.question.id)
               
            else:
                #print("  errorneous_questions is not empty, adding question id")
                quiz_attempt.errorneous_questions += f",{question_attempt.question.id}"
                
            quiz_attempt.save()
            return Response({
                "message": "QuestionAttempt updated successfully. Question was errorneous.",
                "question_attempt_id": pk,
                "question": None,
            })
        
        else:
            # remove question id from errorneous_questions in quiz_attempt if present
            quiz_attempt = question_attempt.quiz_attempt
            if quiz_attempt.errorneous_questions:
                errorneous_questions_array = quiz_attempt.errorneous_questions.split(",")
                if str(question_attempt.question.id) in errorneous_questions_array:
                    errorneous_questions_array.remove(str(question_attempt.question.id))
                    quiz_attempt.errorneous_questions = ",".join(errorneous_questions_array)
                    quiz_attempt.save()
                    
        # if error_flag is true, return, do nothing more
        #if question_attempt.error_flag:
       
        next_question_number = question_attempt.question.question_number + 1
        #print("Next question number to look for:", next_question_number)
        #compare next_question_number last question number in the quiz
        #print("Looking for next question with question number:", next_question_number)
        last_question_in_quiz = question_attempt.quiz_attempt.quiz.questions.order_by('-question_number').first()
        #print(" last question number in quiz is :", last_question_in_quiz.question_number)
        if (next_question_number > last_question_in_quiz.question_number):
            #print("last question number is exceeded:", next_question_number, ">= ", last_question_in_quiz.question_number)
            quiz_attempt = question_attempt.quiz_attempt
            #print(" check errorneous questions array")
            errorneous_questions_array = quiz_attempt.errorneous_questions.split(",") if quiz_attempt.errorneous_questions else []
            #print(" errorneous_questions_array:", errorneous_questions_array)
            #if (quiz_attempt.errorneous_questions is not None) and (quiz_attempt.errorneous_questions != ""):
            if len(errorneous_questions_array) == 0:
                #print(" no errorneous questions to review")
                # mark quiz attempt as completed
                quiz_attempt.completion_status = "completed"
                quiz_attempt.save()
                return Response({
                    "message": "QuestionAttempt updated successfully. No more questions available in the quiz.",
                    "question_attempt_id": pk,
                    "question": None,
                })
            else:
                #print(" there are errorneous questions to review")
                return Response({
                    "message": "No more questions available, but there are errorneous questions to review. Let's redo them.",
                    "question_attempt_id": pk,
                    "question": None,
                })
                
        else :
            # create next QuestionAttempt
            next_question = Question.objects.filter(quiz_id=question_attempt.quiz_attempt.quiz_id, question_number=next_question_number).first()
            if next_question:
                #print("Found next question question id:", next_question.id)
                new_question_attempt = QuestionAttempt.objects.create(
                    quiz_attempt=question_attempt.quiz_attempt,
                    question=next_question,
                    completed=False,
                )
                #print("Created next QuestionAttempt id:", new_question_attempt.id, "for Question id:", next_question.id)
                return Response({
                    "message": "QuestionAttempt updated successfully. Next QuestionAttempt created.",
                    "question_attempt_id": new_question_attempt.id,
                    "question": QuestionSerializer(next_question).data,
                })
            else:
                #print("No next question found, even though not at the end of the quiz.")
                return Response({
                    "message": "QuestionAttempt updated successfully. No more questions available in the quiz.",
                    "question_attempt_id": pk,
                    "question": None,
                })  
            
        # also update the score of the quiz attempt if score is provided
        """
        score = request.data.get('score', None)
        if score is not None:
            quiz_attempt = question_attempt.quiz_attempt
            quiz_attempt.score = score
            quiz_attempt.save()
            print("Updated QuizAttempt id:", quiz_attempt.id, "with new score:", score)
        """
        """
        return Response({
            "message": "QuestionAttempt updated successfully.",
            "question_attempt_id": pk,
            "error_flag": question_attempt.error_flag,
            "completed": question_attempt.completed,
            "score": question_attempt.score,
        })
        """
       
       except QuestionAttempt.DoesNotExist:
              return Response({
                "error": "Question attempt not found."
              }, status=404)
              
    
