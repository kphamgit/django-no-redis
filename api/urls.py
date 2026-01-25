from django.urls import path
from . import views
from django.http import JsonResponse
from .views import CustomTokenObtainPairView, CustomTokenRefreshView, LogoutView, LevelListView

#/api/quizzes/${quizId}/questions/${questionNumber}/`)

urlpatterns = [
    # for authentication using JWT and hppt cookies
    path('api/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/logout/', LogoutView.as_view(), name='logout'),
    path('api/token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    
    path("levels/", LevelListView.as_view(), name="level-list"),
    path("categories/<int:category_id>/units/", views.UnitListView.as_view(), name="unit-list"),
   
    path("quiz_attempts/<int:pk>/", views.create_quiz_attempt),     # pk is quiz_id
    path("quiz_attempts/<int:pk>/create_next_question_attempt/", views.create_question_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/reset/", views.reset_quiz_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/continue/", views.continue_quiz_attempt),  # pk is quiz_attempt_id   
    path("question_attempts/<int:pk>/update/", views.update_question_attempt),  # pk is quiz_attempt_id
    path("question_attempts/<int:pk>/process/", views.process_question_attempt),  # pk is quiz_attempt_id
    path("process_live_question_attempt/", views.process_live_question_attempt),  # pk is quiz_attempt_id
    path("quizzes/<int:quiz_id>/questions/<int:question_number>/", views.get_question_by_number),
] 
   #process_live_question_attempt