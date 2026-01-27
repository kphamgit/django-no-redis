from django.urls import path
from . import views
from django.http import JsonResponse

urlpatterns = [

    # LIST views
    
    path("users/list", views.UserListView.as_view(), name="user-list"),
    path("levels/list", views.LevelListView.as_view(), name="level-list"),
    path("levels/<int:pk>/categories/", views.CategoryListView.as_view(), name="category-list"),
    path("categories/<int:pk>/units/", views.UnitListView.as_view(), name="unit-list"),
    path("units/<int:pk>/quizzes", views.QuizListView.as_view(), name="quiz-list"),
    path("quizzes/<int:pk>/questions", views.QuestionListView.as_view(), name="question-list"),
    
    # end LIST views
    path("quizzes/retrieve/<int:pk>/", views.QuizRetrieveView.as_view(), name="quiz-retrieve"),
    
    # CREATE views
    path("levels/", views.LevelCreateView.as_view(), name="level-create"),
    path("categories/", views.CategoryCreateView.as_view(), name="category-create"),
    path("units/", views.UnitCreateView.as_view(), name="unit-create"),
    path("quizzes/", views.QuizCreateView.as_view(), name="quiz-create"),
    path("questions/", views.QuestionCreateView.as_view(), name="question-create"),
    
    # END CREATE views
    
    # EDIT views
    path("levels/<int:pk>/", views.LevelEditView.as_view(), name="level-edit"),
    path("categories/<int:pk>/", views.CategoryEditView.as_view(), name="category-edit"),
    path("questions/<int:pk>/", views.QuestionEditView.as_view(), name="question-edit"),
    path("quizzes/<int:pk>/", views.QuizEditView.as_view(), name="quiz-edit"),
    path("units/<int:pk>/", views.UnitEditView.as_view(), name="unit-edit"),
    # end EDIT views
    
    path("quiz_attempts/", views.quiz_attempt_list),
    path("quiz_attempts/bulk_delete/", views.quiz_attempt_bulk_delete),
    path("quiz_attempts/<int:pk>/question_attempts/", views.quiz_attempt_get_question_attempts),

    path("items/delete/<int:pk>/", views.ItemDeleteView.as_view(), name="item-delete"),
    # item can be : level, category, sub_category, unit, quiz, question
    # utilities
    path("category/renumber", views.CategoryRenumberView.as_view(), name="categories-renumber"),
    path("level/renumber", views.LevelRenumberView.as_view(), name="levels-renumber"),
    path("unit/renumber", views.UnitRenumberView.as_view(), name="units-renumber"),
    path("quiz/renumber", views.QuizRenumberView.as_view(), name="quizzes-renumber"),
    path("question/renumber", views.QuestionRenumberView.as_view(), name="question-renumber"),


]

