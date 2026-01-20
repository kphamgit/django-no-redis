from django.shortcuts import render

#from django.shortcuts import render
from django.contrib.auth.models import User
from rest_framework import generics
from api.serializers import UserSerializer, LevelWithCategoriesSerializer, \
     UnitWithQuizzesSerializer, QuizAttemptSerializer
from english.serializers import QuestionSerializer
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import Unit, Question, QuizAttempt, QuestionAttempt, Level
from rest_framework.decorators import api_view
from api.utils import check_answer


from rest_framework.response import Response

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
    
class UnitListView(generics.ListAPIView):
    serializer_class = UnitWithQuizzesSerializer
    permission_classes = [IsAuthenticated]
    #permission_classes = [AllowAny]
    

    def get_queryset(self):
        category_id = self.kwargs.get('category_id')
        queryset = Unit.objects.filter(category_id=category_id).order_by('unit_number')
        #print("UnitListView, Filtered Units no Prefetch:", queryset)
        #print("UnitListView, SQL Query:", queryset.query)  # Debugging SQL query
        return queryset
   
@api_view(["GET"])
def get_question_by_number(request, quiz_id, question_number):
    print("get_question_by_number called with quiz_id:", quiz_id, " question_number:", question_number)
    try:
        question = Question.objects.get(quiz_id=quiz_id, question_number=question_number)
        serializer = QuestionSerializer(question)
        return Response(serializer.data)
    except Question.DoesNotExist:
        return Response({
            "error": "Question not found for the given quiz_id and question_number."
        }, status=404)
        
            
@api_view(["POST"])
def create_quiz_attempt(request, pk):
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
        return Response({
            "assessment_results": assessment_results,
        })
        
    except Exception as e:
        return Response({
            "error": f"Error processing answer: {str(e)}"
        }, status=500)

@api_view(["POST"])
def process_question_attempt(request, pk):
    try: 
        #print("process_question_attempt quiz attempt id", pk, " request.data:", request.data)
        assessment_results =  check_answer(request.data.get('format', ''), request.data.get('user_answer', ''), request.data.get('answer_key', ''))
        
        #print(" process_question_attempt, assessment_results:", assessment_results)
        error_flag = assessment_results.get('error_flag', True)
        
        score = 0 if error_flag else 5
        # request.data: {'user_answer': 'test answer', "answer_key": "correct answer"}
        question_attempt = QuestionAttempt.objects.get(id=pk)
        
        question_attempt.error_flag = error_flag
        #print(" process_question_attempt, computed error_flag:", question_attempt.error_flag)
        question_attempt.score = score
        question_attempt.answer = request.data.get('user_answer', '')
        question_attempt.completed = True
        question_attempt.save()
        
        
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
              
    
