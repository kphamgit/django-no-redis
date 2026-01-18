def check_cloze(user_answer, answer_key, options):
    # Placeholder function to check cloze answers
    #print("in check_cloze_answer... user_answer:", user_answer, " answer_key:", answer_key)
    #error = False
    total_score = 0
    answer_key_parts = [part.strip().lower() for part in answer_key.split('/')]
    #print("answer_key_parts:", answer_key_parts)
    user_answer_parts = [part.strip().lower() for part in user_answer.split('/')]
    #print("user_answer_parts:", user_answer_parts)

    # Ensure both arrays are the same size
    if len(user_answer_parts) != len(answer_key_parts):
        #print("Error: user_answer_parts and answer_key_parts are not the same size.")
        return False  # or handle the mismatch appropriately

    # Collect detailed comparison information
    cloze_question_results = []
    for user_part, answer_part in zip(user_answer_parts, answer_key_parts):
        score = 0
        error = False
        is_correct = user_part == answer_part
        if not is_correct:
            error = True
        else:
            score += 5  # Increment score for correct answers

        total_score += score
        cloze_question_results.append({
            "user_answer": user_part,
            "answer_key": answer_part,
            "error_flag": error,
            "score": score,
        })

    #print("Detailed comparison results:", cloze_question_results)

    # Determine overall error
    #overall_error = any(not result["is_correct"] for result in cloze_question_results)

    # Return detailed results, overall error, and score
   
    #return not overall_error 
    return cloze_question_results
            
def check_button_cloze(user_answer, answer_key, options):
    # Placeholder function to check button select answers
    return user_answer.strip().lower() == answer_key.strip().lower()

def check_button_select(user_answer, answer_key, options):
    # Placeholder function to check button select answers
    print("in check_button_select... user_answer:", user_answer, " answer_key:", answer_key)
    error = True
    score = 0
    if user_answer.strip().lower() == answer_key.strip().lower():
        score += 5
        error = False
        
    print("button select result... error:", error, " score:", score)
    return {"error_flag": error, "score": score}
    #return user_answer.strip().lower() == answer_key.strip().lower()

def check_radio(user_answer, answer_key, options):
    print("in check_radio... user_answer:", user_answer, " answer_key:", answer_key)
    error = True
    score = 0
    if user_answer.strip().lower() == answer_key.strip().lower():
        score += 5
        error = False
        
    print("check_radio  result... error:", error, " score:", score)
    return {"error_flag": error, "score": score}
    #return user_answer.strip().lower() == answer_key.strip().lower()

def check_checkbox(user_answer, answer_key, options):
    # Placeholder function to check checkbox answers
    # checkbox has multiple correct answers
    # user answer is a string separated by slashes
    # answer key is a string separated by slashes
    
    error = True
    # iterate through each answer in the answer key
    # and ensure that each answer key is in the user answer
    score = 0
    answer_key_parts = [part.strip().lower() for part in answer_key.split('/')]
    print("answer_key_parts:", answer_key_parts)
   
    user_answer_parts = [part.strip().lower() for part in user_answer.split('/')]
    print("user_answer_parts:", user_answer_parts)
    
    all_correct = True
    for answer_key_part in answer_key_parts:
        if answer_key_part not in user_answer_parts:
            all_correct = False
            
    if all_correct:
        error = False
            
    print("check_checkbox  result... error:", error, " score:", score, " all_correct:", all_correct)
    return {"error_flag": error, "score": score}

    #return user_answer.strip().lower() == answer_key.strip().lower()

def check_words_scramble(user_answer, answer_key, options):
    # user_answer and answer_key are strings separated by slashes
    user_answer_parts = [part.strip().lower() for part in user_answer.split('/')]
    answer_key_parts = [part.strip().lower() for part in answer_key.split('/')]
    
    # if lengths of the two parts are not the same, 
    if len(user_answer_parts) != len(answer_key_parts):
        return {"error_flag": True, "score": 0}
    
    # go through each part and compare, element by element
    error = False
    score = 0
    for user_part, answer_part in zip(user_answer_parts, answer_key_parts):
        if user_part == answer_part:
            score += 5
        else:
            error = True
            
    return {"error_flag": error, "score": score}

    #return user_answer.strip().lower() == answer_key.strip().lower()

def check_speech_recognition(user_answer, answer_key, options):
    # Placeholder function to check speech recognition answers
    return user_answer.strip().lower() == answer_key.strip().lower()

def check_words_select(user_answer, answer_key, options):
   # user answer is a string separated by slashes
    # answer key is a string separated by slashes
    error = True
    # iterate through each answer in the answer key
    # and ensure that each answer key is in the user answer
    score = 0
    print("in check_words_select... user_answer:", user_answer, " answer_key:", answer_key)
    answer_key_parts = [part.strip().lower() for part in answer_key.split('/')]
    print("answer_key_parts:", answer_key_parts)
   
    user_answer_parts = [part.strip().lower() for part in user_answer.split('/')]
    print("user_answer_parts:", user_answer_parts)
    
    all_correct = True
    for answer_key_part in answer_key_parts:
        if answer_key_part not in user_answer_parts:
            all_correct = False
            
    if all_correct:
        error = False
            
    print("check_words_select  result... error:", error, " score:", score, " all_correct:", all_correct)
    return {"error_flag": error, "score": score}

def check_dropdown(user_answer, answer_key, options):
    # Placeholder function to check dropdown answers
    user_answer_parts = [part.strip().lower() for part in user_answer.split('/')]
    answer_key_parts = [part.strip().lower() for part in answer_key.split('/')]
    
    # if lengths of the two parts are not the same, 
    if len(user_answer_parts) != len(answer_key_parts):
        return {"error_flag": True, "score": 0}
    
    # go through each part and compare, element by element
    error = False
    score = 0
    for user_part, answer_part in zip(user_answer_parts, answer_key_parts):
        if user_part == answer_part:
            score += 5
        else:
            error = True
            
    return {"error_flag": error, "score": score}
    #return user_answer.strip().lower() == answer_key.strip().lower()

def check_sentence_scramble(user_answer, answer_key, options):
    # Placeholder function to check sentence scramble answers
    # print("in check_sentence_scramble... user_answer:", user_answer, " answer_key:", answer_key)
    #return user_answer.strip().lower() == answer_key.strip().lower()
    error = False
    score = 0
    if user_answer.strip().lower() == answer_key.strip().lower():
        score += 5
    else:
        error = True
    return {"error_flag": error, "score": score}

def check_answer(format, user_answer, answer_key):
    # Placeholder function to check if the user's answer is correct
    #print("Checking answer... format:", format, " user_answer:", user_answer, " answer_key:", answer_key)
    if format == 1:   #cloze
        #print("Checking cloze answer...")
        cloze_question_results = check_cloze(user_answer, answer_key, options=[])
        #print("Computed cloze question results:", cloze_question_results)
        assessment_results = {
            "error_flag": any(result["error_flag"] for result in cloze_question_results),
            "score": sum(result["score"] for result in cloze_question_results),
            "cloze_question_results": cloze_question_results,
        }
        return assessment_results
    
    elif format == 3:  #button select
        #print("Checking button select answer...")
        results = check_button_select(user_answer, answer_key, options=[])
        return results
    
    elif format == 4:  #radio
        #print("Checking radio answer...")
        results = check_radio(user_answer, answer_key, options=[])
        return results
        
    elif format == 5:  #radio
        #print("Checking check_box answer...")
        results = check_checkbox(user_answer, answer_key, options=[])
        return results
    
    elif format == 6:  #words scramble
        #print("Checking word_scramble answer...")
        results = check_words_scramble(user_answer, answer_key, options=[])
        return results
    
    elif format == 8:  #words select
        #print("Checking word_select answer... user_answer:", user_answer, " answer_key:", answer_key)
        results = check_words_select(user_answer, answer_key, options=[])
        #print("word_select results:", results)
        return results
        
    elif format == 10:  #dropdowns
        #print("Checking drop_down answer... user_answer:", user_answer, " answer_key:", answer_key)
        results = check_dropdown(user_answer, answer_key, options=[])
        #print("drop_down results:", results)
        
    elif format == 12:  #sentence scramble
        #print("Checking sentence scramble answer... user_answer:", user_answer, " answer_key:", answer_key)
        results = check_sentence_scramble(user_answer, answer_key, options=[])
        #print("sentence scramble results:", results)
        
        return results
        
    
        #return check_cloze(user_answer, answer_key, options=[])
        
    