# Create your models here.
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    group = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f'{self.user.username} Profile'

class Note(models.Model):
    title = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notes")

    def __str__(self):
        return self.title

class Level(models.Model):
    name = models.CharField(max_length=100)
    level_number = models.IntegerField()
    
    def __str__(self):
        return self.name
        
class Category(models.Model):
    name = models.CharField(max_length=100)
    category_number = models.IntegerField()
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="categories", default=None, null=True)
    
    def __str__(self):
        return self.name
        
class Unit(models.Model):
    name = models.CharField(max_length=100)
    unit_number = models.IntegerField()
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="units", default=1)
    
    def __str__(self):
        return self.name
    
class Quiz(models.Model):
    name = models.CharField(max_length=100)
    quiz_number = models.IntegerField()
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="quizzes")
    video_url = models.CharField(null=True, blank=True)
    
    def __str__(self):
        return self.name
    
class VideoSegment(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="video_segments")
    segment_number = models.IntegerField(default=0)
    start_time = models.CharField(max_length=50, default="")  # in seconds
    end_time = models.CharField(max_length=50, default="")    # in seconds

    def __str__(self):
        return f"Segment from {self.start_time} to {self.end_time}"
    
class Question(models.Model):
    question_number = models.IntegerField(default=0)
    format = models.PositiveSmallIntegerField(
        validators=[MaxValueValidator(255)], # Restrict range to 0-255
        default=0
    )
    audio_str = models.CharField(max_length=500, blank=True, null=True, default="")
    instructions = models.TextField(max_length=500000, blank=True,null=True, default="")
    prompt = models.TextField(max_length=5000, blank=True,null=True, default="")
    content = models.TextField(max_length=1000, default="")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    video_segment = models.ForeignKey(VideoSegment, on_delete=models.DO_NOTHING, related_name="video_segment_questions", blank=True, null=True)
    answer_key = models.TextField(max_length=500, default="")
    score = models.IntegerField(default=0, null=True)
    timeout = models.IntegerField(default=0, null=True)  # in miliseconds
    button_cloze_options=models.TextField(max_length=200, blank=True, null=True, default="")
    explanation = models.TextField(max_length=1000, blank=True, null=True, default="")
    hint = models.CharField(max_length=500, blank=True, null=True, default="")
    def __str__(self):
        return f"{self.question_number}"
    
class QuizAttempt(models.Model):
    #user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="quiz_attempts")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="quiz_attempts")
    #user_id = models.IntegerField(default=0)
    #quiz_id = models.IntegerField(default=0)
    user_name = models.CharField(max_length=50, default="")
    score = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completion_status = models.CharField(max_length=50, default="uncompleted")  # e.g., "completed", "uncompleted"
    errorneous_questions = models.CharField(max_length=200, blank=True, default="")  # e.g., "1,3,5"
    review_state = models.BooleanField(default=False, null=False)

    def __str__(self):
        return f"{self.user.username} - {self.quiz.name} - {self.score}"
    
class QuestionAttempt(models.Model):
    quiz_attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name="question_attempts")
    #question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="question_attempts")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="question_attempts", default=1)
    error_flag = models.BooleanField(default=None, null=True)
    completed = models.BooleanField(default=False)
    score = models.IntegerField(default=0)
    completed = models.BooleanField(default=False)
    answer = models.CharField(max_length=1000, blank=True, null=True, default="")

    def __str__(self):
        return f"Attempt for {self.question.question_number}"
    
class DictEntry(models.Model):
    head_word = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.head_word
    
class PartOfSpeech(models.Model):
    name = models.CharField(max_length=50, unique=True)
    pron_code = models.CharField(max_length=50, blank=True, null=True)  # british pronunciation code
    amevar_pron = models.CharField(max_length=50, blank=True, null=True)  # american variant pronunciation code
    frequency = models.CharField(max_length=20, blank=True, null=True)
    grammar = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.name
    
class Sense(models.Model):
    pos = models.ForeignKey(PartOfSpeech, on_delete=models.CASCADE, related_name="senses")
    sense_number = models.SmallIntegerField(default=0)
    definition = models.TextField(max_length=1000, blank=True, null=True)
    def_translation = models.TextField(max_length=1000, blank=True, null=True)
    cross_reference = models.CharField(max_length=400, blank=True, null=True)  # e.g., "title/head_word"
    # cross_reference example:  be rewarded (with something)/be-rewarded-with-something
    grammar = models.CharField(max_length=80, blank=True, null=True)
    related_words = models.CharField(max_length=200, blank=True, null=True)  # e.g., "run, running, ran"

    def __str__(self):
        return f"{self.pos.name} - Sense {self.sense_number}"
    
class Example(models.Model):
    sense = models.ForeignKey(Sense, on_delete=models.CASCADE, related_name="examples")
    example_number = models.SmallIntegerField(default=0)
    difficulty_level = models.SmallIntegerField(default=0)  # e.g., 0 for easy, 1 for medium..5 for hard
    sentence = models.TextField(max_length=1000, blank=True, null=True)
    translation = models.TextField(max_length=1200, blank=True, null=True)
    grammar_point = models.CharField(max_length=100, blank=True, null=True)  # e.g., "be rewarded (with something)"

    def __str__(self):
        return f"{self.sense.lcode_entry.head_word} - Example {self.example_number}"
    
    