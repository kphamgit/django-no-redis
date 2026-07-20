from django.urls import path
from . import views
from django.http import JsonResponse
from english import views as english_views


#/api/quizzes/${quizId}/questions/${questionNumber}/`)

urlpatterns = [
    
    path('send-notification/', views.send_notification, name='send_notification'),

    # Forgot / reset password — DEV ONLY (no token, insecure; localhost use)
    path("account/lookup/", views.lookup_account, name="account-lookup"),
    path("account/reset-password/", views.reset_password, name="reset-password"),

    # Forgot / reset password — SECURE token-based flow (production-ready shape)
    path("account/request-reset/", views.request_password_reset, name="request-password-reset"),
    path("account/confirm-reset/", views.confirm_password_reset, name="confirm-password-reset"),
    
    path("levels/", views.level_list, name="level-list"),
    path("categories/<int:category_id>/units/", views.UnitListView.as_view(), name="unit-list"),
    path("quizzes/<int:pk>/", views.QuizDetailView.as_view(), name="quiz-detail"),  # pk is quiz_id
    #TextToSpeechView
    
    #path("text_to_speech_openai/", views.speak, name="text-to-speech"),
    path("text_to_speech_openai/", views.speak_realtime, name="text-to-speech"),
    #path("text_to_speech_azure/", views.generate_azure_audio, name="text-to-speech-azure"),
    path("speech-to-text/", views.openai_transcription, name="speech-to-text"),
    
    #Amazon S3
    path("upload-audio/", views.upload_audio, name="upload-audio"),
   
    path("create_eleven_lab_audio/", views.generate_eleven_lab_audio_and_save_to_azure, name='generate_save_eleven_lab_audio_to_azure'),
  
    #Microsoft Azure Text-to-Speech
    path("create-azure-audio/", views.create_azure_audio, name="create-azure-audio"),
    
    #mark_completed
    path("video_quiz_attempts/create/", views.create_video_quiz_attempt),     # pk is quiz_id
    
    path("video_segments/<int:pk>/get_questions/", views.get_video_segment_questions),     # pk is quiz_id
    path("video_segments/<int:pk>/next_question/", views.get_next_segment_question, name="next-segment-question"),  # pk is video_segment_id
    
    # path("/<int:pk>/questions/<int:starting_question_number>/<int:number_of_questions>/", views.QuestionRangeListView.as_view(), name="question-range-list"),
    
    
    path("quiz_attempts/get_or_create/<int:pk>/", views.get_or_create_quiz_attempt),     # pk is quiz_id
    path("quiz_attempts/get_or_create_react_native/<int:pk>/", views.get_or_create_quiz_attempt_react_native),   
    # path("quiz_attempts/<int:pk>/create_next_question_attempt/", views.create_question_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/create_question_attempt/", views.create_question_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/create_next_question_attempt/", views.create_next_question_attempt), 
    path("quiz_attempts/<int:pk>/reset/", views.reset_quiz_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/mark_completed/", views.mark_quiz_attempt_completed),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/set_review_mode/", views.set_review_mode),  # pk is quiz_attempt_id
    # api.get(`/api/quiz_attempts/${quizAttempt?.id}/incorrect_questions/`) //replenish_incorrect_questions
    path("quiz_attempts/<int:pk>/get_incorrect_question_attempt/", views.get_next_incorrect_question_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/incorrect_count/", views.get_incorrect_count, name="incorrect-count"),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/incorrect_questions/", views.get_incorrect_questions),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/replenish_incorrect_questions/", views.replenish_incorrect_questions),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/replenish_incorrect_questions_react_native/", views.replenish_incorrect_questions_react_native),  # pk is quiz_attempt_id
    
    path("quiz_attempts/<int:pk>/continue/", views.continue_quiz_attempt),  # pk is quiz_attempt_id   
  
    path("video_question_attempts/<int:pk>/process/", views.process_video_question_attempt),  # pk is quiz_attempt_id
    path("question_attempts/<int:pk>/process/", views.process_question_attempt),  # pk is quiz_attempt_id
    path("question_attempts/<int:pk>/process_timeout/", views.process_timeout),  # pk is quiz_attempt_id
    path("process_live_question_attempt/", views.process_live_question_attempt),  # pk is quiz_attempt_id
    path("start_live_quiz/<int:pk>/", views.start_live_quiz),  # pk is live quiz_id
    path("send_live_question_number/<int:pk>/", views.send_live_question_number),  # pk is live question number
    path("quizzes/<int:quiz_id>/questions/<int:question_number>/", views.get_question_by_number),
    path("quizzes/<int:quiz_id>/questions/<int:question_number>/live/", views.get_question_by_number_live),
    path("assignments/pending/", views.get_pending_assignments, name="pending-assignments"),
    path("users/<int:user_id>/assignments/", views.get_user_assignments, name="user-assignments"),
    path("assignment_students/<int:assignment_student_id>/", views.delete_assignment_student, name="delete-assignment-student"),
  
    path("cards/", english_views.CardCreateView.as_view(), name="card-create"),
    path("quizzes/<int:quiz_id>/cards/", views.get_quiz_cards, name="quiz-cards"),
    path("cards/<int:card_id>/delete/", views.delete_card, name="delete-card"),
    path("quizzes/<int:quiz_id>/cards/due/", views.get_due_cards, name="due-cards"),
    path("cards/due/", views.get_all_due_cards, name="all-due-cards"),
    path("cards/<int:card_id>/review/", views.review_card, name="review-card"),
    path("quizzes/<int:quiz_id>/cards/reset/", views.reset_card_progress, name="reset-card-progress"),

    # use only by tienganhbabbel
    path("question_attempts/<int:pk>/update/", views.update_question_attempt),  # pk is quiz_attempt_id
    
    #/api/video_question_attempts/261/process/
    #live_question_number
] 
   #process_live_question_att
   #process_live_question_attempt