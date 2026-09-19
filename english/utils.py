import os
from pystardict import Dictionary

import boto3
from botocore.config import Config
import azure.cognitiveservices.speech as speechsdk
from azure.storage.blob import BlobServiceClient, ContentSettings
from django.conf import settings

def get_s3_audio_url(file_key):
    s3_client = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version='s3v4')
    )
    return s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': file_key},
        ExpiresIn=3600
    )

VOICE_MAP = {
    'en': 'en-US-JennyNeural',
    'fr': 'fr-FR-DeniseNeural',
}

import re as _re

# --- Pronunciation audio blob naming (the SINGLE source of truth) ---------------------------
# These mirror the old TypeScript audioBlobName.ts exactly (verified byte-for-byte against the
# JS djb2). The backend now owns this logic so the two frontends can just read the stored name
# instead of re-deriving it. If you change this, nothing else needs to change.

def hash_pron(s):
    """Deterministic short token for an IPA string (djb2 -> base36), matching JS charCodeAt.
    IPA symbols are all in the BMP, so ord(ch) == JS charCodeAt(i)."""
    h = 5381
    for ch in s:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF  # keep 32-bit unsigned, like JS `>>> 0`
    if h == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while h:
        out = digits[h % 36] + out
        h //= 36
    return out

def clean_pron(pron):
    """First pronunciation variant only, trimmed, with a single stray trailing period dropped."""
    return _re.sub(r'\.$', '', (pron or '').split(',')[0].strip())

def pos_blob_name(word, pron):
    """Azure blob name (no extension) for a word's pronunciation audio.
    has pron -> "{word}_{hash(pron)}" (dedupes identical-sounding POS); no pron -> "{word}"."""
    base = _re.sub(r'\s+', '_', (word or '').strip()).lower()
    phoneme = clean_pron(pron)
    return f"{base}_{hash_pron(phoneme)}" if phoneme else base

def synthesize_azure_audio(text, blob_name=None, language='en', slow=False, phoneme=None):
    """Synthesize text to speech and upload to Azure Blob. Returns blob URL or None on failure."""
    # print(f"Starting audio synthesis for text: '{text}' in language '{language}' with slow={slow}")
    if blob_name is None:
        blob_name = f"fr_{text}" if language != 'en' else text
    if slow:
        blob_name = f"slow_{blob_name }"
    voice_name = VOICE_MAP.get(language, 'en-US-JennyNeural')
    full_blob_name = f"{blob_name}.mp3"
    # print(f"[synthesize_azure_audio] text='{text}' phoneme='{phoneme}' -> blob='{full_blob_name}'")

    # print(f"Generating audio for text: '{text}' with voice '{voice_name}' and blob name '{full_blob_name}'")
    blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    blob_client = blob_service_client.get_blob_client(container="tts-audio", blob=full_blob_name)
 
    if blob_client.exists():
        return blob_client.url

    speech_config = speechsdk.SpeechConfig(
        subscription=settings.AZURE_SPEECH_KEY,
        region=settings.AZURE_SERVICE_REGION
    )
    speech_config.speech_synthesis_voice_name = voice_name
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz128KBitRateMonoMp3
    )

    pull_stream = speechsdk.audio.PullAudioOutputStream()
    audio_config = speechsdk.audio.AudioOutputConfig(stream=pull_stream)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

    if slow or phoneme:
        # Build the inner content, optionally wrapping the word in an IPA phoneme
        # so heteronyms (e.g. record noun vs verb) get their correct pronunciation.
        inner = text
        if phoneme:
            inner = f'<phoneme alphabet="ipa" ph="{phoneme}">{text}</phoneme>'
        if slow:
            inner = f'<prosody rate="slow">{inner}</prosody>'
        ssml = (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{language}">'
            f'<voice name="{voice_name}">'
            f'{inner}'
            f'</voice></speak>'
        )
        result = synthesizer.speak_ssml_async(ssml).get()
    else:
        result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        blob_client.upload_blob(
            result.audio_data,
            overwrite=True,
            content_settings=ContentSettings(content_type='audio/mpeg')
        )
        return blob_client.url

    print("Audio synthesis failed for text:", text, "Reason:", result.reason)
    return None


def tts_blob_exists(blob_name):
    """Return True if "<blob_name>.mp3" already exists in the tts-audio container.
    Lets callers tell the client whether audio was newly created or already present."""
    blob_service_client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    blob_client = blob_service_client.get_blob_client(container="tts-audio", blob=f"{blob_name}.mp3")
    return blob_client.exists()

# 1. Provide the base name (no extension) 
# Example: if your file is 'eng-vie.ifo', use 'eng-vie'
VI_ENG_DICT_BASE_NAME = "en_vi"
FRA_ENG_DICT_BASE_NAME = "fra-eng" 

def read_star_dict(word):
    # print(" read_viet_dict ENTRY word", word)
    if not os.path.exists(f"{VI_ENG_DICT_BASE_NAME}.ifo"):
        print(f"Error: Could not find {VI_ENG_DICT_BASE_NAME}.ifo in the current folder.")
        return

    print(f"--- Loading {VI_ENG_DICT_BASE_NAME} ---")
    sd_dict = Dictionary(VI_ENG_DICT_BASE_NAME)
    
    # 2. Print metadata
    # print(f"&&&&&&&& Total Words: {len(sd_dict)}")
    
    # 3. Print the first 5 entries to see the data structure
    """
    print("\n--- First 5 Entries ---")
    for i, (word, definition) in enumerate(sd_dict.items()):
        if i >= 10: break
        
        # StarDict often returns definitions as bytes, so we decode them
        clean_def = definition
        print(f"WORD: {word}")
        print(f"DEFINITION: {clean_def[:100]}...") # Print first 100 chars
    print("-" * 20)
    """
    if word in sd_dict:
        # print(f"\nLookup Test [{word}]:")
        #print(sd_dict[word])
        entry = sd_dict[word]
        entry_dict = {}
        # print(f"\nEntry for '{word}':", entry)
        entry_dict[word] = {}
        # look in entry for a star *
        # split entry by stars
        # create an empty python dictionary
       
        # iterate thought entry and look for stars. If a star is found, create a new key named "pos" in the dictionary with the text after the star as the key 
        current_pos = None
        collect_line = True
        line_number = 0
        for line in entry.splitlines():
            # print(f"Processing line: {line}")
            line = line.strip()
            if line.startswith("*"):    # new part_of_speech section
                in_idioms_section = False
                part_of_speech = line[1:].strip()
                # print(f" ************** Found new part of speech: {part_of_speech}")
                if (part_of_speech == "danh từ"):
                    part_of_speech = "noun"
                elif ("động từ" in part_of_speech):
                    part_of_speech = "verb"
                # use pos as key to entry_dict[word]
                entry_dict[word][part_of_speech] = {"senses": [], "idioms": []}  # make a new entry for pos in the dictionary,
                current_pos = part_of_speech    # current part_of_speech (either noun, verb, etc.) will be used to determine which pos the following definitions and examples belong to in the dictionary
            # if line starts with "-", it is a definition, add it to the list of definitions for the current pos
            elif line.startswith("-"):
                #print(f" ************** Found definition for pos {current_pos}: {line}")
                # add the definition to the list of definitions for the current pos in the dictionary
                if (collect_line):  # only collect definition lines when collect_line is True and we are not in the idioms section
                    if ( not in_idioms_section):
                        new_sense = {'def': line[1:].strip()}
                        entry_dict[word][current_pos]["senses"].append(new_sense)  # remove the leading "-" and add to the list of definitions for the current pos in the dictionary
                    else:  #  there must have been an idiom section before this definition, so this definition should belong to the last idiom in the idioms list of the current pos in the dictionary, add it as a translation to that idiom
                        current_idiom = entry_dict[word][current_pos]["idioms"][-1]  # get the last idiom in the idioms list of the current pos in the dictionary
                        current_idiom["translation"] = line[1:].strip()  # remove the leading "-" and add it as the translation of the current idiom
                        entry_dict[word][current_pos]["idioms"][-1] = current_idiom  # update the last idiom in the idioms list of the current pos in the dictionary with the new translation
                        
            elif line.startswith("="):
                if entry_dict[word][current_pos]["senses"]:  # only if there's at least one sense
                    if "examples" not in entry_dict[word][current_pos]["senses"][-1]:
                        entry_dict[word][current_pos]["senses"][-1]["examples"] = []
                    entry_dict[word][current_pos]["senses"][-1]["examples"].append(line[1:].strip())
                
            elif line.startswith("!"):  
                # print(f" ^^^^^^^^^^^ Found IDIOM section: {line}")
                in_idioms_section = True
                idiom_dict = {"phrase": line[1:].strip()}
                if "idioms" not in entry_dict[word][current_pos]:
                    entry_dict[word][current_pos]["idioms"] = []
                    
                entry_dict[word][current_pos]["idioms"].append(idiom_dict)
                 
            elif line.startswith("@") and "Chuyên ngành" in line:
                if (line_number > 0):
                    # print(f" ************** Found CHUYEN NGANH section: {line}")
                    collect_line = False
               
            line_number += 1
        
        # print()
        return entry_dict
        
    else:
        print(f"\nWord '{word}' not found in this dictionary.")

import requests
from bs4 import BeautifulSoup

import pyphen

# Build the hyphenation dictionary once at import and reuse it (building it per
# call is wasteful). British (en_GB) patterns match Longman/Cambridge, e.g.
# "dictionary" -> "dic-tion-ary" (en_US would give "dic-tio-nary").
_pyphen_dic = pyphen.Pyphen(lang='en_GB')


def hyphenation(word):
    # Returns the word with hyphens at valid break points, e.g. "dic-tion-ary".
    return _pyphen_dic.inserted(word)

def scrape_longman_url(url):
    # 1. Send a request to the URL
    # We add a 'User-Agent' so the website thinks we are a real browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        
        # Check if the request was successful (Status Code 200)
        response.raise_for_status() 

        # 2. Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')

        # 3. Extract some data
        # print(f"--- Data from: {url} ---")
        
        # Get the Title of the page
        title = soup.title.string if soup.title else "No Title Found"
        # print(f"Page Title: {title}\n")

        # Get all links (<a> tags)
        # print("First 5 links found:")
        links = soup.find_all('a', href=True)
        for link in links[:5]:
            print(f"- {link['href']}")
            
        # look for all divs with ids that contain the string partofspeech
        # print("\nPart of Speech Sections:")
        # look for all divs with ids that has class "POS"
      
        return soup
                
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")


# ---------------------------------------------------------------------------
# Syllabification via the CMU Pronouncing Dictionary (standalone 'cmudict' pkg).
# ---------------------------------------------------------------------------
# The 'cmudict' PyPI package bundles the data (no nltk.download / no corpus
# files to ship), so this works on a fresh Heroku dyno out of the box.
# IMPORTANT: cmudict is PHONETIC — it maps a word to ARPAbet pronunciation
# phonemes, not to spelled-out letters. So this gives an accurate syllable
# COUNT and a phonetic syllable breakdown (e.g. "dictionary" -> D IH1 K / SH
# AH0 / N EH2 / R IY0), NOT a letter split like "dic-tion-ar-y". For letter-
# based hyphenation use hyphenation() above.
import cmudict as _cmudict_lib

_cmudict = None  # lazily loaded + cached (building the dict isn't free)


def _get_cmudict():
    global _cmudict
    if _cmudict is None:
        _cmudict = _cmudict_lib.dict()
    return _cmudict


# Consonant clusters (ARPAbet) that are legal English syllable onsets. Used to
# decide, for consonants sitting between two vowels, how many attach to the
# following syllable's onset (maximal-onset principle) vs. the previous coda.
# Single consonants are always legal onsets, so only 2-/3-clusters are listed.
_LEGAL_ONSETS = {
    # stop / fricative + liquid or glide
    ("P", "R"), ("P", "L"), ("B", "R"), ("B", "L"), ("T", "R"), ("D", "R"),
    ("K", "R"), ("K", "L"), ("G", "R"), ("G", "L"), ("K", "W"), ("G", "W"),
    ("T", "W"), ("D", "W"), ("P", "W"), ("F", "R"), ("F", "L"), ("TH", "R"),
    ("TH", "W"), ("SH", "R"), ("HH", "W"),
    # s + consonant
    ("S", "P"), ("S", "T"), ("S", "K"), ("S", "M"), ("S", "N"), ("S", "L"),
    ("S", "W"), ("S", "F"),
    # consonant + Y glide (e.g. "cute" = K Y UW1)
    ("P", "Y"), ("B", "Y"), ("K", "Y"), ("G", "Y"), ("F", "Y"), ("V", "Y"),
    ("HH", "Y"), ("M", "Y"), ("N", "Y"), ("L", "Y"), ("T", "Y"), ("D", "Y"),
    ("TH", "Y"), ("S", "Y"),
    # three-consonant onsets
    ("S", "P", "R"), ("S", "P", "L"), ("S", "T", "R"), ("S", "K", "R"),
    ("S", "K", "W"), ("S", "P", "Y"), ("S", "K", "Y"), ("S", "T", "Y"),
    ("S", "M", "Y"),
}


def _split_consonant_cluster(cluster):
    """Split a run of consonants between two vowels into (coda, onset), keeping
    the onset as long as it stays a legal English onset (maximal onset)."""
    for cut in range(len(cluster) + 1):
        onset = cluster[cut:]
        if len(onset) <= 1 or tuple(onset) in _LEGAL_ONSETS:
            return cluster[:cut], onset
    return cluster, []


def syllabify(word):
    """Break an English word into phonetic syllables using the CMU dict.

    Returns:
      {
        "word": <input>,
        "found": bool,                     # False if the word isn't in cmudict
        "syllable_count": int,             # reliable (= number of vowel phonemes)
        "phonemes": [...],                 # ARPAbet of the first pronunciation
        "syllables": [["D","IH1","K"], ...]# phonemes grouped per syllable
      }
    NOTE: phonetic syllables (ARPAbet), not spelled-out letters. Use
    hyphenation() for letter-based splitting like "dic-tion-ar-y".
    """
    key = (word or "").strip().lower()
    pronunciations = _get_cmudict().get(key) if key else None
    if not pronunciations:
        return {"word": word, "found": False, "syllable_count": 0, "phonemes": [], "syllables": []}

    phonemes = pronunciations[0]  # first (most common) pronunciation
    nuclei = [i for i, p in enumerate(phonemes) if p[-1].isdigit()]  # vowels carry a stress digit
    if not nuclei:
        return {"word": word, "found": True, "syllable_count": 0, "phonemes": phonemes, "syllables": [phonemes]}

    # Syllable start indices. First syllable starts at 0 (leading consonants are
    # its onset); each following syllable starts after the previous coda.
    boundaries = [0]
    for k in range(len(nuclei) - 1):
        between = phonemes[nuclei[k] + 1:nuclei[k + 1]]
        coda, _onset = _split_consonant_cluster(between)
        boundaries.append(nuclei[k] + 1 + len(coda))
    boundaries.append(len(phonemes))

    syllables = [phonemes[boundaries[i]:boundaries[i + 1]] for i in range(len(nuclei))]
    return {
        "word": word,
        "found": True,
        "syllable_count": len(nuclei),
        "phonemes": phonemes,
        "syllables": syllables,
    }


# ---------------------------------------------------------------------------
# ARPAbet -> Vietnamese pronunciation mapping (experimental / in progress).
# ---------------------------------------------------------------------------
# Maps CMU/ARPAbet phoneme codes to approximate Vietnamese syllables so an
# English word's pronunciation can be shown to Vietnamese learners. Each code
# maps to a LIST of candidates, since one ARPAbet sound can be written several
# ways in Vietnamese (e.g. "AH0" -> "Ớ" or "Ấ"). Only a couple of entries for
# now — add more as the approach is validated.
ARPABET_VOWELS_TO_VIETNAMESE = {
    "AA0": ["o"], "AA1": ["ó"],"AA2": ["ó"],"AA9": ["ò"],
    "AE0": ["a"],"AE1": ["á"],"AE2": ["á"],"AE9": ["à"],
    "AH0": ["ơ", "â"],
    "AH1": ["ớ", "ấ"],
    "AH2": ["ớ", "ấ"],
    "AH9": ["ờ","ầ"],
    "AO0": ["ô", "o"],"AO1": ["ố", "ó"],"AO2": ["ố", "ó"],"AO9": ["ồ", "ò"],
    "AW0": ["ao"],"AW1": ["áo"],"AW2": ["áo"], "AW9": ["ào"],
    "AX0": ["ơ"],"AX1": ["ờ"],"AX2": ["ờ"], "AX9": ["ờ"],
    "AXR0": ["ơ"],"AXR1": ["ờ"],"AXR2": ["ờ"],
    "AY0": ["ai"],"AY1": ["ái"],"AY2": ["ái"],"AY9": ["ài"],
    "EH0": ["e"],"EH1": ["é"],"EH2": ["é"], "EH9": ["è"],
    "ER0": ["ơr"],"ER1": ["ớr"],"ER2": ["ớr"],"ER9": ["ờr"],
    "EY0": ["ay"],"EY1": ["áy"],"EY2": ["ay"], "EY9": ["ày"],
    "IH0": ["i"],"IH1": ["í"],"IH2": ["i"], "IH9": ["ì"],
    "IX0": ["iz"],"IX1": ["íz"],"IX2": ["íz"],"IX9": ["ìz"],
    "IY0": ["i"],"IY1": ["í"],"IY2": ["í"], "IY9": ["ì"],
    "OW0": ["âu", "ơu"],"OW1": ["ấu", "ớu"],"OW2": ["ấu", "ớu"],"OW9": ["ầu", "ờu"],
    "OY0": ["ôi"],"OY1": ["ối",],"OY2": ["ối"],"OY9": ["ồi"],
    "UH0": ["u"],"UH1": ["ú"],"UH2": ["ú"], "UH9": ["ù"],
    "UW0": ["u"],"UW1": ["ú"],"UW2": ["ú"],  "UW9": ["ù"],
    "UX0": ["u"],"UX1": ["ú"],"UX2": ["ú"], "UX9": ["ù"],
}

optional_r_array = ['ố', 'ó', 'ò', 'ơ', 'ồ']

ARPABET_CONSONANTS_TO_VIETNAMESE_EXCEPTIONS = {
    "HH": ["h"],
    "D": ["đ"],
    "W": ["qu"],
}

# 
FINAL_CONSONANT_INDICATOR = ['ai', 'ái', 'ay', 'áy', 'ôi', 'oi']

# --- Contextual add-on rules ------------------------------------------------
# Some Vietnamese renderings depend on a phoneme's NEIGHBOURS, not just the
# phoneme itself, so the flat ARPABET_VOWELS_TO_VIETNAMESE table can't express them.
# A "context rule" looks at the phoneme sequence at position i and either:
#   - returns (candidates, consumed) to OVERRIDE the default for that span, or
#   - returns None to decline (fall through to the next rule / the table).
# `candidates` is the list of Vietnamese alternatives for the span; `consumed`
# is how many phonemes it used up (>=1). Rules are tried in order, first match
# wins. To add a new exception: write a small function and append it to
# _CONTEXT_RULES below.

def _vowel_stress(p):
    """Return the ARPAbet stress digit ('0'/'1'/'2') of a vowel, else None (consonant)."""
    return p[-1] if p and p[-1].isdigit() else None


def _base_code(p):
    """ARPAbet code without its stress digit, e.g. 'IH1' -> 'IH', 'L' -> 'L'."""
    return p[:-1] if _vowel_stress(p) is not None else p


def _rule_ih_before_l(phonemes, i):
    """IH immediately followed by an L -> 'iu' / 'íu' (stressed), absorbing the L
    (the trailing 'u' already carries the dark-L). e.g. bill -> "b íu".
    Fires on any IH+L regardless of syllable position.
    """
    p = phonemes[i]
    if _base_code(p) == "IH" and i + 1 < len(phonemes) and phonemes[i + 1] == "L":
        vowel = "íu" if _vowel_stress(p) in ("1", "2") else "iu"
        return [vowel], 2
    return None


# Register add-on rules here (order matters: first match wins).
_CONTEXT_RULES = [
    _rule_ih_before_l,
]


def arpabet_to_vietnamese(phonemes):
    """Render a run of ARPAbet phonemes as its distinct Vietnamese alternatives.

    Each phoneme maps to a list of Vietnamese candidates (e.g. "AH1" -> ["ớ","ấ"]),
    but contextual rules in _CONTEXT_RULES can override a span first (e.g. IH+L
    -> "iu"). We then build two complete renderings — the first uses each slot's
    1st candidate, the second its 2nd (falling back to the 1st) — and drop
    duplicates. So "bat" -> ["<B> á <T>"], "but" (AH1 -> ớ/ấ) -> ["<B> ớ <T>",
    "<B> ấ <T>"], "bill" (IH+L rule) -> ["<B> íu"]. Unknown codes appear as "<CODE>".
    """
    # Build output "slots": one candidate-list per output position. A context
    # rule may override (and consume several phonemes); otherwise use the table.
    # We also parenthesize a syllable-final (coda) rhotic r, which is optionally
    # pronounced: a standalone coda R -> "(r)", and the r baked into a rhotic ER
    # vowel -> "ơ(r)". "Coda" = after the syllable's vowel; an onset R (before the
    # vowel, e.g. "tr" or [R IY0]) keeps a plain "r".
    slots = []
    i = 0
    n = len(phonemes)
    seen_vowel = False   # has the syllable's nucleus been passed yet?
    while i < n:
        for rule in _CONTEXT_RULES:
            match = rule(phonemes, i)
            if match is not None:
                candidates, consumed = match
                slots.append(candidates)
                if any(ph[-1:].isdigit() for ph in phonemes[i:i + consumed]):
                    seen_vowel = True
                i += max(1, consumed)   # guard against a rule reporting 0
                break
        else:
            p = phonemes[i]
            if p == "R" and seen_vowel:
                slots.append(["(r)"])                       # optional coda R
            elif p.startswith("ER"):
                cands = ARPABET_VOWELS_TO_VIETNAMESE.get(p, [p.lower()])
                slots.append([c[:-1] + "(r)" if c.endswith("r") else c for c in cands])
                seen_vowel = True
            else:
                # Vowel table first; then the consonant exceptions table (e.g.
                # "D" -> "đ", "HH" -> "h", "W" -> "qu"); otherwise a plain
                # lowercase fallback, e.g. "B" -> "b", "NG" -> "ng".
                slots.append(
                    ARPABET_VOWELS_TO_VIETNAMESE.get(p)
                    or ARPABET_CONSONANTS_TO_VIETNAMESE_EXCEPTIONS.get(p)
                    or [p.lower()]
                )
                if p[-1:].isdigit():
                    seen_vowel = True
            i += 1

    def render(idx):
        return "".join(c[idx] if idx < len(c) else c[0] for c in slots)

    # dict.fromkeys de-duplicates while preserving order, collapsing the two
    # renderings to one when there is no genuine second alternative.
    return list(dict.fromkeys([render(0), render(1)]))


def word_to_vietnamese(word, part_of_speech=None):
    """Convert an English word to its Vietnamese pronunciation alternatives, with
    syllables joined by "-". Syllabifies the word, runs the phonemes through
    modify_arpabet (POS- and syllable-count-aware adjustments), converts each
    syllable via arpabet_to_vietnamese, then builds up to two word-level
    alternatives (each syllable's 1st vs 2nd rendering) and de-duplicates.
    Returns [] if the word isn't in cmudict. e.g. "about" -> ["ơ-<B> áo <T>",
    "ờ-<B> áo <T>"].

    Single source of truth used by both the populate view and the serializer, so
    the returned value and the stored viet_pron_code stay in the same format.
    """
    result = syllabify(word)
    if not result["found"] or not result["syllables"]:
        return []

    syllables = result["syllables"]
    # POS/syllable-count-aware adjustment of the raw phonemes before conversion.
    phonemes = modify_arpabet(result["phonemes"], part_of_speech, result["syllable_count"], word)

    # Re-split the (possibly modified) phonemes onto the original syllable
    # boundaries when the total length is unchanged (the common case); if a rule
    # added/removed phonemes, fall back to treating the whole thing as one span.
    lengths = [len(s) for s in syllables]
    if sum(lengths) == len(phonemes):
        regrouped, k = [], 0
        for length in lengths:
            regrouped.append(phonemes[k:k + length])
            k += length
    else:
        regrouped = [phonemes]

    per_syllable = [arpabet_to_vietnamese(s) for s in regrouped]

    # Double-r words (spelling contains "rr"): the r-colored ER vowel bakes its
    # /r/ onto the end of its syllable, which arpabet_to_vietnamese renders as an
    # optional "ơ(r)". For these words the r is actually pronounced as the ONSET
    # of the next syllable ("kớ-rơnt"), so when a syllable ends in an ER* phoneme
    # and a syllable follows, drop the optional "(r)" and prepend a plain "r" to
    # every rendering of the next syllable.
    if "rr" in word.lower():
        for i in range(len(regrouped) - 1):
            if regrouped[i] and regrouped[i][-1].startswith("ER"):
                per_syllable[i] = [a[:-3] if a.endswith("(r)") else a for a in per_syllable[i]]
                per_syllable[i + 1] = ["r" + a for a in per_syllable[i + 1]]

    alternatives = [
        "-".join(alts[idx] if idx < len(alts) else alts[0] for alts in per_syllable)
        for idx in (0, 1)
    ]

    # Post-processing on the formed pronunciation: a word-final "l" (dark L) is
    # pronounced "ồ" in Vietnamese, set off with a hyphen, e.g. "ball" -> "bố-ồ"
    # -- UNLESS the character before it is already "ồ" (e.g. "mammal" -> "má-mồl"
    # stays as is).
    def _final_l_to_o(s):
        if s.endswith("l") and not s[:-1].endswith("ồ"):
            return s[:-1] + "-ồ"
        return s

    alternatives = [_final_l_to_o(a) for a in alternatives]
    return list(dict.fromkeys(alternatives))


def modify_arpabet(phonemes, part_of_speech=None, syllable_count=None, word=None):
    """Adjust an ARPAbet phoneme sequence based on the word's part of speech,
    its number of syllables, and its spelling, BEFORE it is converted to Vietnamese.

    Args:
        phonemes: list of ARPAbet codes, e.g. ["R", "IH0", "K", "AO1", "R", "D"].
        part_of_speech: e.g. "noun", "verb" (heteronyms like record differ by POS).
        syllable_count: number of syllables in the word.
        word: the spelled word, for suffix-based rules (e.g. -ic/-sion/-tion).
    Returns:
        The (possibly modified) list of ARPAbet codes.
    """
    # print(f"[modify_arpabet] part_of_speech={part_of_speech!r} "
    #       f"syllable_count={syllable_count} word={word!r} phonemes={phonemes}")

    # Rule: T-flapping / alveolar tap. A "T" becomes a "D" (-> Vietnamese "đ")
    # when it sits between two vowel sounds AND the following vowel is unstressed:
    #   - preceding phoneme is a vowel OR "R" (the r sound counts as a vowel here),
    #   - following phoneme is an unstressed vowel (stress digit 0).
    # e.g. water (AO1 T ER0) -> wa-der, party (R T IY0) -> par-dy.
    # Runs first so it reads the original cmudict stress. When cmudict already
    # spells a -tion/-tial "sh" as SH (nation = ...SH AH0 N), there is no T to
    # touch, so that case is handled automatically.
    for i in range(1, len(phonemes) - 1):
        if phonemes[i] == "T":
            prev = phonemes[i - 1]
            nxt = phonemes[i + 1]
            prev_is_vowel_sound = prev[-1:].isdigit() or prev == "R"
            next_is_unstressed_vowel = nxt[-1:] in ("0", "2")  # stress 0 or secondary 2
            if prev_is_vowel_sound and next_is_unstressed_vowel:
                phonemes[i] = "D"

    # Rule: a 2-syllable "giới từ" (preposition), "phó từ" (adverb) or verb ->
    # first syllable's stress digit becomes 9, second syllable's becomes 0. Each
    # syllable's stress lives on its vowel (a code ending in a stress digit
    # 0/1/2), so we rewrite the 1st vowel's digit to 9 and the 2nd vowel's to 0;
    # consonants are left untouched.
    # NB: read_star_dict renames "động từ" -> "verb" upstream, so we match "verb".
    if part_of_speech in {"giới từ", "phó từ", "verb"} and syllable_count == 2:
        adjusted = []
        vowel_index = 0
        for p in phonemes:
            if p[-1].isdigit():
                p = p[:-1] + ("9" if vowel_index == 0 else "0")
                vowel_index += 1
            adjusted.append(p)
        phonemes = adjusted

    # Rule: a word ending in ...AH0 L (e.g. lethal, mammal) -> the final AH0
    # becomes AO9. The last syllable is word-final, so this is just the last two
    # phonemes being ["AH0", "L"].
    if phonemes[-2:] == ["AH0", "L"]:
        phonemes = phonemes[:-2] + ["AO9", "L"]

    # Rule: a consonant + "Y" + "UW1" (the /ju:/ glide, e.g. cute K Y UW1 T,
    # computer ... P Y UW1 ...) -> render as Vietnamese "íu": the stress belongs
    # on the "i", so make the "Y" the stressed vowel (IY1 -> "í") and demote the
    # "UW1" to unstressed (UW0 -> "u"). Otherwise you'd get "iú" (accent on u).
    adjusted = []
    i = 0
    while i < len(phonemes):
        if (phonemes[i] == "Y" and phonemes[i + 1:i + 2] == ["UW1"]
                and i > 0 and not phonemes[i - 1][-1:].isdigit()):
            adjusted.extend(["IY1", "UW0"])
            i += 2
        else:
            adjusted.append(phonemes[i])
            i += 1
    phonemes = adjusted

    # Rule: words ending in -ic, -sion, -tion take stress on the penultimate
    # syllable (e-co-nom-ic, lo-ca-tion, re-vi-sion), so the LAST syllable is
    # unstressed -> set its vowel's stress digit to 9. The last syllable's vowel
    # is the last phoneme ending in a stress digit.
    if word and word.lower().endswith(("ic", "sion", "tion")):
        for j in range(len(phonemes) - 1, -1, -1):
            if phonemes[j][-1:].isdigit():
                phonemes[j] = phonemes[j][:-1] + "9"
                break

    # Rule: words ending in -ory, -ary, -ery (repository, necessary, bakery) or
    # -rry (carry, merry, hurry, sorry) -> the final "y" vowel (usually IY0)
    # should carry stress 9. Same action: set the last vowel's stress digit to 9.
    if word and word.lower().endswith(("ory", "ary", "ery", "rry")):
        for j in range(len(phonemes) - 1, -1, -1):
            if phonemes[j][-1:].isdigit():
                phonemes[j] = phonemes[j][:-1] + "9"
                break

    # Rule: multi-syllable words ending in "-o" (potato, tomato) stress the
    # penultimate syllable, so the final "o" is unstressed -> set its vowel's
    # stress digit to 9 (cmudict marks it 2). Runs after T-flapping so the flap
    # still sees the original stress-2 vowel. Guard: skip when the final vowel
    # already has PRIMARY stress 1 (e.g. hello = ...OW1), since there the last
    # syllable really is stressed.
    if word and syllable_count and syllable_count > 1 and word.lower().endswith("o"):
        for j in range(len(phonemes) - 1, -1, -1):
            if phonemes[j][-1:].isdigit():
                if phonemes[j][-1] != "1":
                    phonemes[j] = phonemes[j][:-1] + "9"
                break

    # print(f"[modify_arpabet] modified phonemes={phonemes}")
    return phonemes
