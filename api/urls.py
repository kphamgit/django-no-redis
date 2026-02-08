from django.urls import path
from . import views
from django.http import JsonResponse

#/api/quizzes/${quizId}/questions/${questionNumber}/`)

urlpatterns = [
    
    path('send-notification/', views.send_notification, name='send_notification'),
    
    path("levels/", views.level_list, name="level-list"),
    path("categories/<int:category_id>/units/", views.UnitListView.as_view(), name="unit-list"),
    path("quizzes/<int:pk>/", views.QuizDetailView.as_view(), name="quiz-detail"),  # pk is quiz_id
   
    path("video_quiz_attempts/", views.create_video_quiz_attempt),     # pk is quiz_id
    path("quiz_attempts/get_or_create/<int:pk>/", views.get_or_create_quiz_attempt),     # pk is quiz_id
    path("quiz_attempts/<int:pk>/create_next_question_attempt/", views.create_question_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/reset/", views.reset_quiz_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/continue/", views.continue_quiz_attempt),  # pk is quiz_attempt_id   
    path("question_attempts/<int:pk>/update/", views.update_question_attempt),  # pk is quiz_attempt_id
    path("video_question_attempts/<int:pk>/process/", views.process_video_question_attempt),  # pk is quiz_attempt_id
    path("question_attempts/<int:pk>/process/", views.process_question_attempt),  # pk is quiz_attempt_id
    path("process_live_question_attempt/", views.process_live_question_attempt),  # pk is quiz_attempt_id
    path("quizzes/<int:quiz_id>/questions/<int:question_number>/", views.get_question_by_number),
   
    #/api/video_question_attempts/261/process/
] 
   #process_live_question_attempt