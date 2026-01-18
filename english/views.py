# Create your views here.
from django.shortcuts import render
from api.models import Question, Quiz, Unit, Level, Category, QuizAttempt, QuestionAttempt
from .serializers import CategorySerializer, UnitSerializer, QuizSerializer, QuestionSerializer, LevelSerializer
from api.serializers import QuizAttemptSerializer, QuestionAttemptSerializer
from .serializers import UserSerializer
from django.contrib.auth.models import User
from rest_framework.permissions import IsAuthenticated
from rest_framework import generics
from rest_framework.decorators import api_view


# Create your views here.
   
#  VIEWS

from django.http import JsonResponse
from django.views.decorators.csrf import get_token

def get_csrf_token(request):
    print("get_csrf_token called request =", request)
    my_token = get_token(request)
    print("CSRF token:", my_token)
    return JsonResponse({"token": my_token})


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

class QuestionListView(generics.ListAPIView):
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]
    #permission_classes = [AllowAny]

    def get_queryset(self):
        pk = self.kwargs.get('pk')
        queryset = Question.objects.filter(quiz_id=pk).order_by('question_number')
        return queryset

class QuestionCreateView(generics.ListCreateAPIView):
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        #print("perform_create, request data:", self.request.data)
        if serializer.is_valid():
            #serializer.save()
            #kpham: NO NEED for explicit fields since all are included in serializer
            serializer.save( 
                question_number=self.request.data.get('question_number'),
                format=self.request.data.get('format'),
                content=self.request.data.get('content'),
                quiz_id=self.request.data.get('quiz_id'),
                answer_key=self.request.data.get('answer_key'),
                instructions=self.request.data.get('instructions'),
                prompt=self.request.data.get('prompt'),
                audio_str=self.request.data.get('audio_str'),
            )
            
        else:
            print(serializer.errors)

    #fields = ["id", "unit_id", "name", "quiz_number", "questions"]
class QuizCreateView(generics.ListCreateAPIView):
    serializer_class = QuizSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        #print("perform_create, request data:", self.request.data)
        if serializer.is_valid():
            serializer.save(
                unit_id=self.request.data.get('unit_id'),
                quiz_number=self.request.data.get('quiz_number'),
                name=self.request.data.get('name')
            )
        else:
            print(serializer.errors)
            
class UnitCreateView(generics.ListCreateAPIView):
    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
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
            print(f"Quiz attempt with ID {quiz_attempt_id} not found.")
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

class QuestionEditView(generics.RetrieveUpdateAPIView):
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]
    #queryset = Question.objects.filter(question_id=question_id)  # Add this line
    #print("QuestionEditView HERE")
    def perform_update(self, serializer):
        #print("request data:", self.request.data)
        if serializer.is_valid():
            print("Serializer is valid")
            serializer.save()
            """
            serializer.save(
                            audio_str=self.request.data.get('audio_str'),
                            prompt=self.request.data.get('prompt'),
                            content=self.request.data.get('content'),
                            answer_key=self.request.data.get('answer_key')
            )
            """
        else:
            print(serializer.errors)
            
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
            print("Serializer is valid")
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
    
class UnitEditView(generics.RetrieveUpdateAPIView):
    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated]
    #queryset = Question.objects.filter(question_id=question_id)  # Add this line
    def perform_update(self, serializer):
        #print("request data:", self.request.data)
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
        #print("request data:", self.request.data)
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
            

class QuestionRenumberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        print("request data:", self.request.data)
        #request data: {'data_type': 'question', 'id_number_pairs': '[10,4,5,6]'}
        id_numbers = self.request.data.get('id_number_pairs')
        # Convert the string representation of the list to an actual list
        import ast
        id_numbers = ast.literal_eval(id_numbers)
        print("after .... conversion: id_number_pairs:", id_numbers)
      
        for index, question_id in enumerate(id_numbers, start=1):  # Start numbering from 1
            #question_id = question_id
            try:
                question = Question.objects.get(id=question_id)
                question.question_number = index  # Use the index as the new number
                question.save()
                print(f"Updated Question ID {question_id} to new number {index}")
            except Question.DoesNotExist:
                print(f"Question with ID {question_id} does not exist.")
                
        return Response({"message": "Questions renumbered successfully."})
            
from django.apps import apps
    
class ItemDeleteView(generics.DestroyAPIView):
    serializer_class = QuizSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        id = self.kwargs.get('pk')
        # retrieve data_type from query parameters
        print("ItemDeleteView .... request data:", self.request)
        
        data_type = self.request.query_params.get('data_type', 'question').lower() # Default to 'question' if not provided
        #data_type = self.request.data.get('data_type', 'Question') # Default to 'Question' if not provided
        queryset = None
        print("ItemDeleteView get_queryset, data_type:", data_type, ", id:", id)
        if data_type == 'question':
            queryset = Question.objects.filter(id=id) 
        elif data_type == 'quiz':
            print("ItemDeleteView Quiz Delete .... id:", id)
            queryset = Quiz.objects.filter(id=id)
        elif data_type == 'unit':
            queryset = Unit.objects.filter(id=id)
        elif data_type == 'level':
            queryset = Level.objects.filter(id=id)
        elif data_type == 'category':
            queryset = Category.objects.filter(id=id)
            
        
        print("ItemDeleteView get_queryset, queryset:", queryset)
        
        return queryset
    
