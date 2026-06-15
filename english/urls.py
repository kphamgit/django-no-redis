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
    # retrieve questions in a quiz starting from a specific question number
    path("quizzes/<int:pk>/questions/<int:starting_question_number>", views.QuestionPartialListView.as_view(), name="question-list"),
    path("quizzes/<int:pk>/questions/<int:starting_question_number>/<int:number_of_questions>/", views.QuestionRangeListView.as_view(), name="question-range-list"),
    path("quizzes/<int:pk>/video_segments/", views.VideoSegmentListView.as_view(), name="video-segment-list"),
    # for video segments list, pk is quiz_id of the quiz that the video segments belong to
    
    # end LIST views
    path("quizzes/retrieve/<int:pk>/", views.QuizRetrieveView.as_view(), name="quiz-retrieve"),
    
    # CREATE views
    path("levels/", views.LevelCreateView.as_view(), name="level-create"),
    path("categories/", views.CategoryCreateView.as_view(), name="category-create"),
    path("units/", views.UnitCreateView.as_view(), name="unit-create"),
    path("quizzes/", views.QuizCreateView.as_view(), name="quiz-create"),
    path("questions/", views.QuestionCreateView.as_view(), name="question-create"),
    path("video_segments/", views.VideoSegmentCreateView.as_view(), name="video-segment-create"),
    
    # END CREATE views
    
    path("quizzes/<int:pk>/move/", views.move_quiz),  # for moving quiz to different category/unit/level
     path("quizzes/<int:pk>/assign/", views.assign_quiz),
     
    # RETRIEVE views
    path("quizzes/<int:pk>/video_segments/retrieve_by_segment_number/<int:segment_number>/", views.VideoSegmentRetrieveByNumberView.as_view(), name="video-segment-retrieve-by-number"),
    path("video_segments/retrieve/<int:pk>/", views.VideoSegmentRetrieveView.as_view(), name="video-segment-retrieve"),
    
    # only retrieve level info, such as level name and number, without categories 
    path("levels/<int:pk>/", views.LevelRetrieveView.as_view(), name="level-retrieve"),
    path("categories/<int:pk>/", views.CategoryRetrieveView.as_view(), name="category-retrieve"),
    path("units/<int:pk>/", views.UnitRetrieveView.as_view(), name="unit-retrieve"),
    
    # clone views
    path("questions/<int:pk>/clone", views.QuestionCloneView.as_view(), name="question-clone"),
    
    # EDIT views
    path("levels/<int:pk>/edit", views.LevelEditView.as_view(), name="level-edit"),
    path("categories/<int:pk>/edit", views.CategoryEditView.as_view(), name="category-edit"),
    path("questions/<int:pk>/", views.QuestionEditView.as_view(), name="question-edit"),
    path("quizzes/<int:pk>/", views.QuizEditView.as_view(), name="quiz-edit"),
    path("units/<int:pk>/edit", views.UnitEditView.as_view(), name="unit-edit"),
    path("video_segments/<int:pk>/", views.VideoSegmentEditView.as_view(), name="video-segment-edit"),
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
    path("video_segment/renumber", views.VideoSegmentRenumberView.as_view(), name="question-renumber"),
    path("quizzes/<int:quiz_id>/location/", views.quiz_location, name="quiz-location"),

    path("get_recordings/", views.get_recordings, name="get-recordings"),
    path("delete-audio/", views.delete_audio, name="delete-audio"),
    path("batch-delete-files/", views.batch_delete_files, name="batch-delete-files"),
    
    #populate-viet-dictionary
    path("populate-viet-dictionary/", views.populate_viet_dictionary, name="populate-viet-dictionary"),
    path("read-dictionary/", views.read_dictionary, name="read-dictionary"),
    # populate-longman-dictionary
    path("delete-dictionary-entry/", views.delete_dictionary_entry, name="delete-dictionary-entry"),
    path("populate-longman-dictionary/", views.populate_longman_dictionary, name="populate-longman-dictionary"),
    # update-sense
    path("update-dictionary-sense/<int:pk>/", views.SenseUpdateView.as_view(), name="update-dictionary-sense"),
 
    # path("nlp-test/", views.nlp_test, name="nlp-test"),
]

