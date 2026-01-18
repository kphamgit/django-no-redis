from django.urls import path
from . import views
from django.http import JsonResponse

urlpatterns = [
    path("levels/", views.level_list, name="level-list"),
    path("categories/<int:category_id>/units/", views.UnitListView.as_view(), name="unit-list"),
   
    path("quiz_attempts/<int:pk>/", views.create_quiz_attempt),     # pk is quiz_id
    path("quiz_attempts/<int:pk>/create_next_question_attempt/", views.create_question_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/reset/", views.reset_quiz_attempt),  # pk is quiz_attempt_id
    path("quiz_attempts/<int:pk>/continue/", views.continue_quiz_attempt),  # pk is quiz_attempt_id   
    path("question_attempts/<int:pk>/update/", views.update_question_attempt),  # pk is quiz_attempt_id
    path("question_attempts/<int:pk>/process/", views.process_question_attempt),  # pk is quiz_attempt_id
] 
   