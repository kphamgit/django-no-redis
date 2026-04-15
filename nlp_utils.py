import spacy

# Load once when the server starts
# We disable 'lemmatizer' if you don't need it to save more RAM
nlp = spacy.load("en_core_web_sm", disable=["lemmatizer"])

def analyze_user_text(text):
    """
    Processes text and returns a dictionary of results.
    """
    if not text:
        return {"error": "No text provided"}

    doc = nlp(text)
    
    # Extracting named entities (People, Places, Orgs)
    entities = [{"text": ent.text, "label": ent.label_} for ent in doc.ents]
    
    return {
        "original_text": text,
        "entities": entities,
        "token_count": len(doc)
    }