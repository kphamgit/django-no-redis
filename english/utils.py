import os
import unicodedata
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
        in_idioms_section = False   # set before the loop so a stray content line can't read it unbound
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
            elif line.startswith("-") and current_pos is not None:
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
                        
            elif line.startswith("=") and current_pos is not None:
                if entry_dict[word][current_pos]["senses"]:  # only if there's at least one sense
                    if "examples" not in entry_dict[word][current_pos]["senses"][-1]:
                        entry_dict[word][current_pos]["senses"][-1]["examples"] = []
                    entry_dict[word][current_pos]["senses"][-1]["examples"].append(line[1:].strip())
                
            elif line.startswith("!") and current_pos is not None:
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


_moby_hyphenation = None

def _get_moby_hyphenation():
    """Lazily load + cache the Moby Hyphenation List (Grady Ward, public domain,
    Project Gutenberg #3204): 187k words pre-syllabified by lexicographers, so we
    look up letter-syllabification instead of guessing it. The data file
    (english/data/mhyph.txt) is Latin-1 with syllables separated by byte 0xA5 and
    literal hyphens kept as '-'. Returns {plain_lowercased_word: [variant, ...]}.
    A word may list several hyphenations (noun/verb variants); all distinct ones
    are kept, in file order.
    """
    global _moby_hyphenation
    if _moby_hyphenation is None:
        d = {}
        path = os.path.join(os.path.dirname(__file__), "data", "mhyph.txt")
        try:
            with open(path, "rb") as fh:
                for raw in fh:
                    line = raw.decode("latin-1").rstrip("\r\n")
                    if not line:
                        continue
                    key = line.replace("\xa5", "").lower()   # plain word (keeps literal '-')
                    val = line.replace("\xa5", "-")          # "ta\xa5ble" -> "ta-ble"
                    variants = d.setdefault(key, [])
                    # Keep distinct variants, but de-dupe case-insensitively so a
                    # capitalization-only twin (e.g. "He-ro" vs "he-ro") doesn't
                    # look like a real homograph to the stress-override rule.
                    if val.lower() not in [v.lower() for v in variants]:
                        variants.append(val)
        except FileNotFoundError:
            pass
        _moby_hyphenation = d
    return _moby_hyphenation


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


_VOWEL_LETTERS = set("aeiouy")

def _resyllabify_spelling(word, target_count):
    """Re-split WORD's spelling into TARGET_COUNT syllables using vowel positions.

    A best-effort letter-level syllabifier used to correct pyphen's hyphenation
    when it disagrees with cmudict's (reliable) syllable count. Each maximal run
    of vowel letters is treated as one syllable nucleus; the consonants between
    two nuclei are split V-CV (single consonant joins the next syllable) or
    VC-CV (a cluster keeps its first consonant). Returns the hyphenated string,
    or None when the number of vowel groups != target_count (can't map cleanly).
    """
    lower = word.lower()
    # Maximal runs of vowel letters -> one nucleus each.
    groups, i, n = [], 0, len(lower)
    while i < n:
        if lower[i] in _VOWEL_LETTERS:
            j = i
            while j < n and lower[j] in _VOWEL_LETTERS:
                j += 1
            groups.append((i, j))
            i = j
        else:
            i += 1
    if len(groups) != target_count or target_count < 2:
        return None
    # A cut index (hyphen goes before it) within each inter-nucleus consonant run.
    parts, prev = [], 0
    for g in range(len(groups) - 1):
        vend = groups[g][1]          # first consonant after this nucleus
        run = groups[g + 1][0] - vend  # consonants before the next nucleus
        cut = vend if run <= 1 else vend + 1  # V-CV vs VC-CV
        parts.append(word[prev:cut])
        prev = cut
    parts.append(word[prev:])
    return "-".join(parts)


def _moby_or_fallback_variants(word):
    """Return the hyphenation variant(s) for WORD as a list. Primary source is
    the Moby Hyphenation List (lexicographer splits, e.g. ["ta-ble"], or
    ["pres-ent", "pre-sent"]). For words not in Moby, a one-item list with the
    pyphen form corrected against cmudict's syllable count (pyphen alone as a
    last resort).
    """
    key = (word or "").strip().lower()
    moby = _get_moby_hyphenation().get(key)
    if moby:
        return moby

    pyphen_form = hyphenation(word)
    syl = syllabify(word)
    if not syl["found"] or not syl["syllable_count"]:
        return [pyphen_form]
    if pyphen_form.count("-") + 1 == syl["syllable_count"]:
        return [pyphen_form]
    return [_resyllabify_spelling(word, syl["syllable_count"]) or pyphen_form]


def _first_syllable_closed(hyphenated):
    """True if the first syllable ends in a consonant (closed), e.g. "pres-ent";
    False if it ends in a vowel (open), e.g. "pre-sent"."""
    first = hyphenated.split("-", 1)[0]
    return bool(first) and first[-1].lower() not in _VOWEL_LETTERS


def _ends_in_consonant_le(hyphenated):
    """True if the word's last spelled syllable is a consonant + "le" (ble, ple,
    cle, tle, dle, ...), as in "ta-ble", "ap-ple", "lit-tle", "ex-am-ple". Reads
    the last syllable of the per-POS hyphenation (first variant if several joined
    with " / ")."""
    last = (hyphenated or "").split(" / ")[0].split("-")[-1].lower()
    return len(last) >= 3 and last.endswith("le") and last[-3] not in _VOWEL_LETTERS


def corrected_hyphenation(word):
    """All distinct hyphenation variants for WORD, joined (e.g.
    "pres-ent / pre-sent"). POS-agnostic -- see corrected_hyphenation_for_pos."""
    return " / ".join(_moby_or_fallback_variants(word))


def corrected_hyphenation_for_pos(word, part_of_speech=None):
    """Hyphenation chosen for a specific POS. When a word has multiple Moby
    variants, pick by the noun/verb stress pattern: a noun stresses (and closes)
    the first syllable -> "pres-ent"; a verb opens it -> "pre-sent". A single
    variant is returned as-is; any other POS (or no clear match) returns all
    variants joined.
    """
    variants = _moby_or_fallback_variants(word)
    if len(variants) == 1:
        return variants[0]
    if _is_noun(part_of_speech):
        closed = [v for v in variants if _first_syllable_closed(v)]
        if closed:
            return closed[0]
    elif _is_verb(part_of_speech):
        open_first = [v for v in variants if not _first_syllable_closed(v)]
        if open_first:
            return open_first[0]
    return " / ".join(variants)


# ---------------------------------------------------------------------------
# ARPAbet -> Vietnamese pronunciation mapping (experimental / in progress).
# ---------------------------------------------------------------------------
# Maps CMU/ARPAbet phoneme codes to approximate Vietnamese syllables so an
# English word's pronunciation can be shown to Vietnamese learners. Each code
# maps to a LIST of candidates, since one ARPAbet sound can be written several
# ways in Vietnamese (e.g. "AH0" -> "Ớ" or "Ấ"). Only a couple of entries for
# now — add more as the approach is validated.

# "EY0": ["ay"],"EY1": ["áy"],"EY2": ["ay"], "EY9": ["ày"],

ARPABET_VOWELS_TO_VIETNAMESE = {
    "AA0": ["o"], "AA1": ["ó"],"AA2": ["ó"],"AA9": ["ò"],
    "AE0": ["a"],"AE1": ["á"],"AE2": ["á"],"AE9": ["à"],
    "AF0": ["ê"],"AF1": ["ế"],"AF2": ["ế"],"AF9": ["ề"], "AF8": ["ệ"],
    "AH0": ["ơ", "â"],"AH1": ["ớ", "ấ"], "AH2": ["ớ", "ấ"],"AH9": ["ờ","ầ"],
    "AK0": ["o"],"AK1": ["ó"],"AK2": ["ó"],"AK9": ["ò"],
    "AO0": ["ô"],"AO1": ["ố"],"AO2": ["ố"],"AO9": ["ồ"],
    "AW0": ["ao"],"AW1": ["áo"],"AW2": ["áo"], "AW9": ["ào"],
    "AX0": ["ơ"],"AX1": ["ờ"],"AX2": ["ờ"], "AX9": ["ờ"],
    "AXR0":["ơ"],"AXR1": ["ờ"],"AXR2": ["ờ"],
    "AY0": ["ai"],"AY1": ["ái"],"AY2": ["ai"],"AY9": ["ài"],
    "EH0": ["e"],"EH1": ["é"],"EH2": ["é"], "EH9": ["è"],
    "ER0": ["ơr"],"ER1": ["ớr"],"ER2": ["ớr"],"ER9": ["ờr"],
    "EY0": ["ei"],"EY1": ["éi"],"EY2": ["ey"], "EY9": ["èi"],
    "IH0": ["i"],"IH1": ["í"],"IH2": ["i"], "IH9": ["ì", "ề"],
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


def arpabet_to_vietnamese(phonemes, next_phoneme=None):
    """Render a run of ARPAbet phonemes as its distinct Vietnamese alternatives.
    `next_phoneme` is the ARPAbet phoneme that follows this span in the word (or
    None if the span ends the word); it controls whether a rhotic r is
    parenthesized (see below).

    Each phoneme maps to a list of Vietnamese candidates (e.g. "AH1" -> ["ớ","ấ"]),
    but contextual rules in _CONTEXT_RULES can override a span first (e.g. IH+L
    -> "iu"). We then build two complete renderings — the first uses each slot's
    1st candidate, the second its 2nd (falling back to the 1st) — and drop
    duplicates. So "bat" -> ["<B> á <T>"], "but" (AH1 -> ớ/ấ) -> ["<B> ớ <T>",
    "<B> ấ <T>"], "bill" (IH+L rule) -> ["<B> íu"]. Unknown codes appear as "<CODE>".
    """
    # Build output "slots": one candidate-list per output position. A context
    # rule may override (and consume several phonemes); otherwise use the table.
    # A rhotic r is parenthesized as "optionally pronounced" when it is NOT
    # immediately followed by a vowel -- i.e. a coda r at the end of the word
    # (car -> "ko(r)", here -> ...) OR before another consonant (cart -> "ká(r)t",
    # learn -> "lơ(r)n"). A rhotic r FOLLOWED BY A VOWEL is a plain, linking "r"
    # (av-er-age -> "vơr", ve-ry -> "r"); an onset R (before its own vowel) is also
    # a plain "r". The "following phoneme" is the next one in this span, or
    # `next_phoneme` when the r is the span's last phoneme.
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
            following = phonemes[i + 1] if i + 1 < n else next_phoneme
            # Optional (parenthesized) r unless a vowel sound follows (= linking r).
            r_optional = following is None or _vowel_stress(following) is None
            if p == "R" and seen_vowel:
                slots.append(["(r)"] if r_optional else ["r"])   # coda R
            elif p.startswith("ER"):
                cands = ARPABET_VOWELS_TO_VIETNAMESE.get(p, [p.lower()])
                if r_optional:
                    cands = [c[:-1] + "(r)" if c.endswith("r") else c for c in cands]
                slots.append(cands)                          # else keep plain "ơr"
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

    # Fixed spelling fix-ups on the rendered syllable (e.g. the reduced "-age"/
    # "-edge" ending "ệjh" is written "ệt-j(ờ)").
    renders = [r.replace("ệjh", "ệt-j(ờ)") for r in (render(0), render(1))]

    # dict.fromkeys de-duplicates while preserving order, collapsing the two
    # renderings to one when there is no genuine second alternative.
    return list(dict.fromkeys(renders))


def respell_in_vietnamese(word, part_of_speech=None, steps=None, flap_t=True):
    """Convert an English word to its Vietnamese pronunciation alternatives, with
    syllables joined by "-". Syllabifies the word, runs the phonemes through
    modify_arpabet_stress (POS- and syllable-count-aware adjustments), converts each
    syllable via arpabet_to_vietnamese, then builds up to two word-level
    alternatives (each syllable's 1st vs 2nd rendering) and de-duplicates.
    Returns [] if the word isn't in cmudict. e.g. "about" -> ["ơ-<B> áo <T>",
    "ờ-<B> áo <T>"].

    Single source of truth used by both the populate view and the serializer, so
    the returned value and the stored viet_pron_code stay in the same format.

    If `steps` is a list, a detailed step-by-step trace of the whole pipeline is
    appended to it -- each entry is {"title", "value", "detail"} -- for the
    teacher-facing "pipeline" view.
    """
    def _trace(title, value, detail):
        if steps is not None:
            steps.append({"title": title, "value": value, "detail": detail})

    def _disp(psyll):
        # First-alternative assembly of a per-syllable candidate list, for display.
        return "-".join((c[0] if c else "") for c in psyll)

    result = syllabify(word)
    if not result["found"] or not result["syllables"]:
        return []

    syllables = result["syllables"]
    _trace("cmudict ARPABET", " ".join(result["phonemes"]),
           "Raw ARPABET phonemes from cmudict (the first / most common pronunciation). "
           "Each vowel carries a stress digit: 0 = unstressed, 1 = primary, 2 = secondary.")

    # Per-POS corrected (Moby) hyphenation, shared by both passes so they can key
    # off the spelled syllables (e.g. the "-le" ending).
    hyphenated = corrected_hyphenation_for_pos(word, part_of_speech)
    _trace("Hyphenation (per-POS)", hyphenated,
           "Letter syllabification from the Moby list, chosen for this part of speech. The "
           "vowel/stress rules use it to spot endings like \"-le\" and to position a linking r.")

    # Vowel-quality adjustments FIRST, then the stress pass LAST (so stress digits
    # are assigned after the vowel codes are settled).
    phonemes = modify_arpabet_quality(result["phonemes"], part_of_speech, result["syllable_count"], word, hyphenated, flap_t=flap_t)
    _trace("After phoneme-quality rules (modify_arpabet_quality)", " ".join(phonemes),
           "Phoneme-QUALITY changes (base codes, no stress digits): T-flapping (T -> D "
           "between vowels); a consonant+\"-le\" ending's vowel becomes custom \"AO\"; a "
           "reduced \"-age\"/\"-edge\" word's vowel becomes custom \"AF\".")

    phonemes = modify_arpabet_stress(phonemes, part_of_speech, result["syllable_count"], word, hyphenated)
    _trace("After stress rules (modify_arpabet_stress)", " ".join(phonemes),
           "Stress DIGITS: the 2-syllable 1/9 rule (stressed vowel -> 1, reduced vowel -> 9) with a "
           "noun/verb homograph override; a \"-le\" vowel -> 9; a \"-age\"/\"-edge\" vowel -> custom 8; "
           "single-syllable normalization.")

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

    _trace("Syllable grouping", " | ".join(" ".join(s) for s in regrouped),
           "The (modified) phonemes regrouped onto the word's syllable boundaries; each group "
           "is rendered to Vietnamese on its own.")

    # Pass each syllable the first phoneme of the NEXT syllable (None for the last)
    # so a rhotic r is parenthesized only when not followed by a vowel.
    per_syllable = [
        arpabet_to_vietnamese(s, next_phoneme=(regrouped[idx + 1][0] if idx + 1 < len(regrouped) else None))
        for idx, s in enumerate(regrouped)
    ]
    _trace("Per-syllable Vietnamese (arpabet_to_vietnamese)", _disp(per_syllable),
           "Each syllable mapped to Vietnamese via the ARPABET->Vietnamese table plus context "
           "rules. A rhotic r is written \"(r)\" (optional) unless a vowel follows it; the reduced "
           "\"-age\"/\"-edge\" ending \"ệjh\" is written \"ệt-j(ờ)\".")

    # Linking r: an ER vowel immediately before another vowel pronounces its /r/
    # as the ONSET of the next syllable. arpabet_to_vietnamese already rendered
    # that (vowel-followed) r as a PLAIN trailing "r" (e.g. "vơr"); move it off
    # this syllable and prepend it to the next, so av-er-age "á-vơr-ệjh" becomes
    # "á-vơ-rệjh" and current "kơr..." becomes "kơ-rơnt". A coda r shown "(r)"
    # (before a consonant or at word end) is NOT moved.
    _before_r = _disp(per_syllable)
    linked_r_targets = set()  # syllable indices that received a moved-in onset "r"
    for i in range(len(regrouped) - 1):
        if (regrouped[i] and regrouped[i][-1].startswith("ER")
                and any(a.endswith("r") and not a.endswith("(r)") for a in per_syllable[i])):
            per_syllable[i] = [
                a[:-1] if (a.endswith("r") and not a.endswith("(r)")) else a
                for a in per_syllable[i]
            ]
            per_syllable[i + 1] = ["r" + a for a in per_syllable[i + 1]]
            linked_r_targets.add(i + 1)
    if _disp(per_syllable) != _before_r:
        _trace("Linking r moved", _disp(per_syllable),
               "An r between two vowels is pronounced as the onset of the next syllable, so the "
               "plain trailing r is moved there, e.g. \"vơr\" -> \"vơ-r\".")

    # Diphthong (AY/OY/EY/AW/OW) followed by a nasal, rendered as its own syllable:
    #   - coda "N" ANYWHERE -> "ờn", splitting any following coda consonant(s) off
    #     with a hyphen. e.g. fine -> fái-ờn, mind -> mái-ờn-d.
    #   - "M" only at the END of the word -> "ờm". e.g. time -> tái-ờm, home -> hấu-ờm.
    # The N must be a coda (not the onset of a following vowel), so "dining" and
    # "timer" (M is an onset) are unaffected.
    _diphthongs = {"AY", "OY", "EY", "AW", "OW"}
    last_syl_index = len(regrouped) - 1
    expanded = []
    for i, syl in enumerate(regrouped):
        split_at = None
        literal = None
        for j in range(len(syl) - 1):
            if _base_code(syl[j]) not in _diphthongs:
                continue
            nxt = syl[j + 1]
            after = syl[j + 2] if j + 2 < len(syl) else None
            if nxt == "N" and (after is None or not after[-1:].isdigit()):
                split_at, literal = j, "ờn"       # diphthong + coda N (anywhere)
                break
            if nxt == "M" and i == last_syl_index and j + 1 == len(syl) - 1:
                split_at, literal = j, "ờm"       # diphthong + word-final M
                break
        if split_at is None:
            expanded.append(per_syllable[i])
        else:
            onset = arpabet_to_vietnamese(syl[:split_at + 1])           # onset + diphthong
            # If a linking r was moved onto this syllable's onset (e.g. around
            # "ờ-raonđ"), re-add it -- re-rendering from phonemes here would
            # otherwise drop it, giving "ờ-ao-ờn-đ".
            if i in linked_r_targets:
                onset = ["r" + c for c in onset]
            expanded.append(onset)
            expanded.append([literal])                                  # N -> ần / M -> ờm
            coda = syl[split_at + 2:]
            if coda:
                expanded.append(arpabet_to_vietnamese(coda))            # trailing consonant(s)
    if _disp(expanded) != _disp(per_syllable):
        _trace("Diphthong + nasal split", _disp(expanded),
               "A diphthong (AY/OY/EY/AW/OW) before a coda N (or word-final M) is split into its "
               "own syllable \"ờn\"/\"ờm\", e.g. fine -> fái-ờn, time -> tái-ờm.")
    per_syllable = expanded

    alternatives = [
        "-".join(alts[idx] if idx < len(alts) else alts[0] for alts in per_syllable)
        for idx in (0, 1)
    ]
    _trace("Assembled alternatives", " / ".join(dict.fromkeys(alternatives)),
           "Syllables joined with \"-\" into up to two alternatives (each syllable's 1st vs 2nd "
           "candidate), then de-duplicated.")

    # Double "pp"/"bb" in the spelling that cmudict collapsed to a single P/B
    # (apple -> [AE1 P AH0 L]) but the hyphenation keeps on both sides (ap-ple).
    # Add the missing consonant back as a coda on the syllable BEFORE the one that
    # starts with it, so the rendering matches the hyphenation: apple "á-pồl" ->
    # "áp-pồl". Vietnamese has no final "-b", so a "b" coda is written "p"
    # (the following onset stays "b"): nibble "ní-bồl" -> "níp-bồl". (Only "p"/"b";
    # e.g. "gg" is left as is.)
    def _restore_double_consonant(rendering):
        for double, cons in (("pp", "p"), ("bb", "b")):
            if double not in word.lower():
                continue
            coda = "p" if cons == "b" else cons   # no final "-b" in Vietnamese
            parts = rendering.split("-")
            for k in range(1, len(parts)):
                if parts[k].startswith(cons) and not parts[k - 1].endswith(coda):
                    parts[k - 1] = parts[k - 1] + coda
                    break
            rendering = "-".join(parts)
        return rendering

    _before_dbl = list(alternatives)
    alternatives = [_restore_double_consonant(a) for a in alternatives]
    if alternatives != _before_dbl:
        _trace("Double consonant restored", " / ".join(dict.fromkeys(alternatives)),
               "A spelled \"pp\"/\"bb\" that cmudict collapsed to one is added back as a coda to "
               "match the hyphenation (apple -> áp-pồl); a \"b\" coda is written \"p\" since "
               "Vietnamese has no final \"-b\" (nibble -> níp-bồl).")

    # A word-final "l" (dark L) is pronounced "ồ" in Vietnamese, set off with a
    # hyphen, e.g. "ball" -> "bô-ồ" -- UNLESS the char before it is already "ồ"
    # (e.g. "mammal" -> "má-mồl" stays as is).
    def _final_l_to_o(s):
        if s.endswith("l") and not s[:-1].endswith("ồ"):
            return s[:-1] + "-ồ"
        return s

    _before_l = list(alternatives)
    alternatives = [_final_l_to_o(a) for a in alternatives]
    if alternatives != _before_l:
        _trace("Final dark L -> ồ", " / ".join(dict.fromkeys(alternatives)),
               "A word-final \"l\" (dark L) is pronounced \"ồ\", set off with a hyphen "
               "(ball -> bô-ồ), unless the char before it is already \"ồ\" (mammal -> má-mồl).")

    # In Vietnamese "l" only starts a word/syllable, never ends one. So a coda "l"
    # -- an "l" directly after a vowel (ồl, òl, ìl, ...) -- is an optionally
    # pronounced coda, written "(l)" (just like the optional coda r "(r)"): table
    # "táy-bồl" -> "táy-bồ(l)". (An "l" after a consonant, like the onset cluster
    # "bl", or already after a hyphen, is left alone.)
    def _coda_l_to_parens(rendering):
        out = []
        for i, ch in enumerate(rendering):
            if ch == "l" and i > 0:
                base = unicodedata.normalize("NFD", rendering[i - 1])[:1].lower()
                if base in ("a", "e", "i", "o", "u", "y"):
                    out.append("(l)")
                    continue
            out.append(ch)
        return "".join(out)

    _before_coda_l = list(alternatives)
    alternatives = [_coda_l_to_parens(a) for a in alternatives]
    if alternatives != _before_coda_l:
        _trace("Coda l -> (l)", " / ".join(dict.fromkeys(alternatives)),
               "Vietnamese \"l\" only starts a syllable, so an \"l\" directly after a vowel "
               "(a coda l, e.g. \"ồl\") is written as an optional \"(l)\" -- like the optional "
               "coda r \"(r)\" -- giving table -> táy-bồ(l).")

    # A coda "v" -- a "v" NOT followed by a vowel (word end, a hyphen, or a
    # consonant) -- is an optionally pronounced coda, written "(v)" (like coda
    # "(l)"/"(r)"). This is the English "v + silent e" case: have -> ha(v),
    # move -> mu(v), movement -> mú(v)-mờn-t, lovely -> lớ(v)-lì:. An onset v
    # (followed by a vowel) stays plain: oven "ớ-vờn", level "lé-vồ(l)".
    def _coda_v_to_parens(rendering):
        out = []
        for i, ch in enumerate(rendering):
            if ch == "v":
                nxt = rendering[i + 1] if i + 1 < len(rendering) else ""
                base = unicodedata.normalize("NFD", nxt)[:1].lower() if nxt else ""
                if base not in ("a", "e", "i", "o", "u", "y"):
                    out.append("(v)")
                    continue
            out.append(ch)
        return "".join(out)

    _before_coda_v = list(alternatives)
    alternatives = [_coda_v_to_parens(a) for a in alternatives]
    if alternatives != _before_coda_v:
        _trace("Coda v -> (v)", " / ".join(dict.fromkeys(alternatives)),
               "A \"v\" not followed by a vowel (the English \"v + silent e\" case) is an "
               "optional coda, written \"(v)\" -- have -> ha(v), movement -> mú(v)-mờn-t. "
               "An onset v (before a vowel) stays plain (oven -> ớ-vờn).")

    # Drop any alternative that has an OPEN syllable ending in "â"/"ấ"/"ầ": these
    # don't exist in Vietnamese -- the â-vowel always needs a coda or a glide.
    # Keep valid alternatives; fall back to the unfiltered list if all are invalid.
    _open_a_endings = ("â", "ấ", "ầ")
    def _has_open_a_syllable(rendering):
        return any(syllable.endswith(_open_a_endings) for syllable in rendering.split("-"))
    _before_filter = list(alternatives)
    filtered = [a for a in alternatives if not _has_open_a_syllable(a)]
    alternatives = filtered or alternatives
    if alternatives != _before_filter:
        _trace("Drop open-â alternatives", " / ".join(dict.fromkeys(alternatives)),
               "Alternatives with an OPEN syllable ending in \"â\"/\"ấ\"/\"ầ\" are dropped "
               "(that vowel needs a coda or glide in Vietnamese); if all would be dropped, "
               "the unfiltered list is kept.")
    # Word-initial "t" (not followed by "h") is the ASPIRATED t, shown as "t(h)"
    # (e.g. top -> t(h)óp). A plain "t" -- the NON-ASPIRATED t -- is left as is,
    # e.g. a "t" after a consonant ("stop") or the "th" digraph.
    _before_th = list(alternatives)
    alternatives = [
        "t(h)" + a[1:] if a.startswith("t") and not a.startswith("th") else a
        for a in alternatives
    ]
    if alternatives != _before_th:
        _trace("Aspirated t", " / ".join(dict.fromkeys(alternatives)),
               "A word-initial \"t\" (not \"th\") is the ASPIRATED t, written \"t(h)\" "
               "(e.g. top -> t(h)óp). A plain \"t\" -- the NON-ASPIRATED t -- is left as is "
               "(a \"t\" after a consonant, e.g. \"stop\", or the \"th\" digraph).")

    # (No aspirated-"p" rule: an aspirated "p" isn't a sound Vietnamese uses, so a
    # word-initial "p" is left plain -- unlike the aspirated "t"/"k" above/below.)

    # A word-initial "k" is the ASPIRATED k, written "k(h)" (e.g. key -> k(h)í:,
    # cat -> k(h)át). A "k" that is not word-initial -- the NON-ASPIRATED k -- is
    # left as is: a "k" after "s" (sky, ski) and a word-medial "k" both stay plain.
    _before_kh = list(alternatives)
    alternatives = [
        "k(h)" + a[1:] if a.startswith("k") and not a.startswith("k(h)") else a
        for a in alternatives
    ]
    if alternatives != _before_kh:
        _trace("Aspirated k", " / ".join(dict.fromkeys(alternatives)),
               "A word-initial \"k\" is the ASPIRATED k, written \"k(h)\" (e.g. cat -> "
               "k(h)át). A NON-ASPIRATED k -- after \"s\" (sky/ski) or word-medial -- is "
               "left as is.")

    # A word-final "sh" isn't a valid Vietnamese coda, so split it off with a
    # hyphen: wash -> quó-sh. (A final "ch" IS valid, so teach -> t(h)ích stays.)
    _before_sh = list(alternatives)
    alternatives = [a[:-2] + "-sh" if a.endswith("sh") else a for a in alternatives]
    if alternatives != _before_sh:
        _trace("Final sh split", " / ".join(dict.fromkeys(alternatives)),
               "A word-final \"sh\" isn't a valid Vietnamese coda, so it's set off with a "
               "hyphen (wash -> quó-sh). A final \"ch\" IS valid, so teach -> t(h)ích stays.")

    # A word-final coda "đ" (D), "g" (G) or "s" (S/ss) isn't a valid Vietnamese
    # coda, so set it off with a hyphen: had -> há-đ, dog -> đố-g, kiss -> ki-s.
    _final_coda_split = ("đ", "g", "s")
    _before_coda = list(alternatives)
    alternatives = [
        a[:-1] + "-" + a[-1]
        if a.endswith(_final_coda_split) and not a[:-1].endswith("-") else a
        for a in alternatives
    ]
    if alternatives != _before_coda:
        _trace("Final coda split (đ/g/s)", " / ".join(dict.fromkeys(alternatives)),
               "A word-final \"đ\" (D), \"g\" (G) or \"s\" (S/ss) isn't a valid Vietnamese "
               "coda, so it's set off with a hyphen (had -> há-đ, dog -> đố-g, kiss -> ki-s).")

    # An "ớ"/"ấ" vowel directly before a split coda "-s" takes an added "t" coda:
    # "kớ-s" -> "kớt-s", "kấ-s" -> "kất-s".
    _before_ts = list(alternatives)
    alternatives = [a.replace("kớ-s", "kớt-s").replace("kấ-s", "kất-s") for a in alternatives]
    if alternatives != _before_ts:
        _trace("Insert t before coda s", " / ".join(dict.fromkeys(alternatives)),
               "\"kớ-s\" becomes \"kớt-s\" and \"kấ-s\" becomes \"kất-s\": the ớ/ấ vowel takes "
               "an added \"t\" coda before the split coda \"s\".")

    # EXPERIMENTAL (added last so it's easy to remove): a WORD-FINAL coda "t"/"p"
    # that sits directly after a vowel is marked for its released final stop,
    # branching on the nucleus:
    #   - monophthong (one vowel letter) -> REPEAT the stop:  bất -> bất-t, bóp -> bóp-p
    #   - diphthong (two+ vowel letters) -> SPLIT the stop:   báot -> báo-t
    # Only the LAST syllable is considered, so a t/p ending a non-final syllable is
    # left alone (stoppage, average, discuss). A stop after a consonant (a cluster
    # like "st" in "post") is also left untouched.
    def _is_vowel_char(ch):
        return unicodedata.normalize("NFD", ch)[:1].lower() in ("a", "e", "i", "o", "u", "y")

    def _final_stop_rule(rendering):
        parts = rendering.split("-")
        p = parts[-1]
        if len(p) >= 2 and p[-1] in ("t", "p") and _is_vowel_char(p[-2]):
            # length of the trailing vowel run (the nucleus before the coda)
            run = 0
            for ch in reversed(p[:-1]):
                if _is_vowel_char(ch):
                    run += 1
                else:
                    break
            parts[-1] = p[:-1] + "-" + p[-1] if run >= 2 else p + "-" + p[-1]
        return "-".join(parts)

    _before_stop = list(alternatives)
    alternatives = [_final_stop_rule(a) for a in alternatives]
    if alternatives != _before_stop:
        _trace("Final stop (t/p) marked", " / ".join(dict.fromkeys(alternatives)),
               "A coda \"t\"/\"p\" right after a vowel is marked: repeated after a monophthong "
               "(bất -> bất-t, bóp -> bóp-p) or split off after a diphthong (báot -> báo-t). "
               "A stop after a consonant (cluster, e.g. \"post\") is left as is.")

    # Split a coda "t" off an "ờn"/"ần"/"ền" + t sequence with a hyphen:
    # "ờnt" -> "ờn-t", "ầnt" -> "ần-t", "ềnt" -> "ền-t" (e.g. current -> k(h)ớ-rờn-t).
    _before_nt = list(alternatives)
    alternatives = [
        a.replace("ờnt", "ờn-t").replace("ầnt", "ần-t").replace("ềnt", "ền-t")
        for a in alternatives
    ]
    if alternatives != _before_nt:
        _trace("Split nt (ờn/ần/ền + t)", " / ".join(dict.fromkeys(alternatives)),
               "A coda \"t\" after \"ờn\"/\"ần\"/\"ền\" is set off with a hyphen "
               "(\"ờnt\" -> \"ờn-t\"), e.g. current -> k(h)ớ-rờn-t.")

    # "úk" isn't a valid Vietnamese spelling (the coda /k/ after "u" is written "c"),
    # so rewrite it as "úc-k": the proper coda "úc" plus a split-off released "-k".
    # e.g. look "lúk" -> "lúc-k", book "búk" -> "búc-k".
    _before_uk = list(alternatives)
    alternatives = [a.replace("úk", "úc-k") for a in alternatives]
    if alternatives != _before_uk:
        _trace("úk -> úc-k", " / ".join(dict.fromkeys(alternatives)),
               "\"úk\" isn't valid Vietnamese (coda /k/ after \"u\" is written \"c\"), so it "
               "becomes \"úc-k\" -- the coda \"úc\" plus a split released \"-k\" (look -> lúc-k).")

    # A word-final "ú-đ" takes an added "t" coda: "ú-đ" -> "út-đ" (the "u" vowel
    # needs a stop coda before the released -đ). e.g. mood "mú-đ" -> "mút-đ".
    _before_uud = list(alternatives)
    alternatives = [a[:-3] + "út-đ" if a.endswith("ú-đ") else a for a in alternatives]
    if alternatives != _before_uud:
        _trace("Final ú-đ -> út-đ", " / ".join(dict.fromkeys(alternatives)),
               "A word-final \"ú-đ\" becomes \"út-đ\" -- the \"u\" vowel takes an added \"t\" "
               "coda before the released \"-đ\" (mood -> mút-đ, stood -> stút-đ).")

    final = list(dict.fromkeys(alternatives))
    _trace("Final viet_pron_code", " / ".join(final),
           "The de-duplicated alternatives, stored as the viet_pron_code.")
    return final

def _is_noun(part_of_speech):
    """True if the POS label denotes a noun -- English "noun" or the Vietnamese
    "danh từ" the stardict source uses. Exact/prefix match so "pronoun" / "đại từ"
    (pronoun) don't count."""
    p = (part_of_speech or "").strip().lower()
    return p == "noun" or p.startswith("danh từ")


def _is_verb(part_of_speech):
    """True if the POS label denotes a verb -- English "verb" or the Vietnamese
    "động từ" the stardict source uses."""
    p = (part_of_speech or "").strip().lower()
    return p == "verb" or p.startswith("động từ")


# Words whose final "-age"/"-edge" is the reduced /ɪdʒ/ sound (like "message",
# "knowledge"), NOT the /eɪdʒ/ of "age", "page", "cage". Used by
# modify_arpabet_quality and modify_arpabet_stress to special-case that final
# syllable's vowel/stress.
AGE_EDGE_REDUCED_WORDS = {
    "acknowledge", "advantage", "assemblage", "average", "baggage", "beverage", "cabbage",
    "cottage", "courage", "coverage", "damage", "disadvantage", "dosage",
    "drainage", "encourage", "garbage", "hostage", "image", "knowledge",
    "language", "lineage", "luggage", "manage", "message", "miscarriage",
    "mortgage", "package", "parentage", "passage", "percentage", "pilgrimage",
    "postage", "privilege", "salvage", "shortage", "spillage", "slippage", "stoppage",
    "storage", "tutelage", "usage", "village", "vintage", "voyage",
}


def modify_arpabet_stress(phonemes, part_of_speech=None, syllable_count=None, word=None, hyphenated=None):
    if hyphenated is None and word is not None:
        hyphenated = corrected_hyphenation_for_pos(word, part_of_speech)
    if syllable_count == 2:
        # Two-syllable words: mark the stressed vowel "1" and the unstressed vowel
        # with the custom code "9" (defined in ARPABET_VOWELS_TO_VIETNAMESE).
        # Which syllable is stressed comes from cmudict by default (reliable for a
        # word's normal pronunciation). EXCEPTION: a POS-dependent homograph -- a
        # word Moby lists with more than one hyphenation (present, record, desert)
        # -- has its stress overridden from the per-POS hyphenation: a closed first
        # syllable ("pres-ent") stresses syllable 1, an open one ("pre-sent")
        # stresses syllable 2. This is the only case where cmudict's single default
        # is wrong for one of the parts of speech.
        nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
        if len(nuclei) == 2:
            # Default: whichever nucleus cmudict marks with primary stress "1".
            stressed = next((idx for idx, i in enumerate(nuclei, 1)
                             if _vowel_stress(phonemes[i]) == "1"), 1)
            # Override for homographs (multiple Moby variants + a noun/verb POS).
            key = (word or "").strip().lower()
            variants = _get_moby_hyphenation().get(key) if key else None
            if variants and len(variants) > 1 and (_is_noun(part_of_speech) or _is_verb(part_of_speech)):
                stressed = 1 if _first_syllable_closed(hyphenated or "") else 2
            # --- The "1/9" rule ---------------------------------------------
            # Having decided WHICH syllable is stressed (above), stamp the two
            # vowels' stress digits to a binary scheme: the stressed vowel gets
            # "1", the other (reduced) vowel gets the custom "9". Consonants are
            # untouched, phonemes are neither added nor removed, and the stress
            # POSITION isn't changed here -- we only rewrite the two digits.
            # cmudict's original 0/1/2 digits are replaced: stressed -> "1",
            # unstressed -> "9" (e.g. "R IY0 M UW1 V" -> "R IY9 M UW1 V"). The
            # "9" is a custom code whose ARPABET_VOWELS_TO_VIETNAMESE entries give
            # the reduced syllable a falling (huyền) tone in Vietnamese. This runs
            # for every two-syllable word with no exceptions -- a "-le" vowel that
            # modify_arpabet_quality changed to "AO" simply becomes "AO9" here.
            phonemes = list(phonemes)
            for idx, i in enumerate(nuclei, 1):
                phonemes[i] = _base_code(phonemes[i]) + ("1" if idx == stressed else "9")
    if syllable_count == 1:
        # A one-syllable word has a single vowel; its stress is meaningless, so
        # normalize the vowel's stress digit to 0 (e.g. "BEE" B IY1 -> B IY0).
        # EXCEPTION: keep the stress only for a closed syllable whose coda is
        # EXACTLY ONE consonant from the keep-set -- "CAT" K AE1 T, "BAD" B AE1 D,
        # "CAP" K AE1 P, "BOOK" B UH1 K, "KISS" K IH1 S. A multi-consonant coda
        # ("BAND" B AE1 N D, "BANK" B AE1 NG K, "STRENGTH" ...) still normalizes to 0.
        _KEEP_STRESS_FINAL = ("T", "D", "P", "G", "K", "S", "Z")
        # Coda = the consonants after the single vowel (nucleus).
        _vowel_idx = next((i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None), None)
        _coda = phonemes[_vowel_idx + 1:] if _vowel_idx is not None else []
        keep_stress = len(_coda) == 1 and _base_code(_coda[0]) in _KEEP_STRESS_FINAL
        if not keep_stress:
            phonemes = [
                _base_code(p) + "0" if _vowel_stress(p) is not None else p
                for p in phonemes
            ]
    if syllable_count == 3:
        # Three-syllable words: trust cmudict for WHICH syllable is stressed (don't
        # move the stress), but extend the 2-syllable 1/9 treatment to the reduced
        # syllables -- every UNSTRESSED vowel (cmudict digit "0") becomes the custom
        # "9" (huyền tone), e.g. consider "K AH0 N S IH1 D ER0" -> "...AH9...IH1...ER9".
        # Primary "1" and SECONDARY "2" (a full vowel, as in -ize/-ate endings:
        # organize "AO1 ...AH0... AY2") are left alone so a secondary-stressed syllable
        # isn't over-reduced to huyền.
        phonemes = [
            _base_code(p) + "9" if _vowel_stress(p) == "0" else p
            for p in phonemes
        ]

    # Consonant + "-le" ending ("ta-ble", "ap-ple", "ex-am-ple", "hor-ri-ble"):
    # the final "-le" syllable is reduced, so apply the 1/9 rule to it -- stamp its
    # vowel with stress "9" -- REGARDLESS of the word's syllable count. For a
    # 2-syllable word the branch above already did this; this extends it to 3+-
    # syllable words (whose earlier syllables are still left to cmudict for now).
    # syllable_count is available here so the digit can be fine-tuned by length
    # later if needed (e.g. a different reduction for very long words).
    if _ends_in_consonant_le(hyphenated):
        nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
        if nuclei:
            le_digit = "9"   # reduced final "-le" syllable
            # Hook: branch on syllable_count here to fine-tune le_digit when needed.
            phonemes = list(phonemes)
            phonemes[nuclei[-1]] = _base_code(phonemes[nuclei[-1]]) + le_digit

    # Reduced "-age"/"-edge" word (AGE_EDGE_REDUCED_WORDS, e.g. "message",
    # "knowledge"): the final syllable gets stress digit "8" -- overriding the "9"
    # the 1/9 rule put there -- regardless of syllable count. (modify_arpabet_quality
    # already set its vowel code to "AF", so it becomes "AF8".)
    if (word or "").strip().lower() in AGE_EDGE_REDUCED_WORDS:
        nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
        if nuclei:
            phonemes = list(phonemes)
            phonemes[nuclei[-1]] = _base_code(phonemes[nuclei[-1]]) + "8"

    # Any word ending in "-ity" (quality, ability, hostility, city): the final
    # "y" vowel is reduced, so set its stress digit to 9 -- e.g. ability
    # "AH0 B IH1 L AH0 T IY2" -> "...T IY9".
    if (word or "").strip().lower().endswith("ity"):
        nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
        if nuclei:
            phonemes = list(phonemes)
            phonemes[nuclei[-1]] = _base_code(phonemes[nuclei[-1]]) + "9"

    # Words ending in -ic, -sion, -tion take stress on the penultimate syllable
    # (e-co-nom-ic, lo-ca-tion, re-vi-sion), so the LAST syllable is unstressed ->
    # set its vowel's stress digit to 9.
    if (word or "").strip().lower().endswith(("ic", "sion", "tion")):
        nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
        if nuclei:
            phonemes = list(phonemes)
            phonemes[nuclei[-1]] = _base_code(phonemes[nuclei[-1]]) + "9"

    # Words ending in -ory, -ary, -ery (repository, necessary, bakery) or -rry
    # (carry, merry, hurry, sorry) -> the final "y" vowel should carry stress 9.
    if (word or "").strip().lower().endswith(("ory", "ary", "ery", "rry")):
        nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
        if nuclei:
            phonemes = list(phonemes)
            phonemes[nuclei[-1]] = _base_code(phonemes[nuclei[-1]]) + "9"

    # Multi-syllable words ending in "-o" (potato, tomato) stress the penultimate
    # syllable, so the final "o" is unstressed -> set its vowel's stress digit to 9.
    # Guard: skip when the final vowel already has PRIMARY stress 1 (e.g. hello =
    # ...OW1), where the last syllable really is stressed.
    if word and syllable_count and syllable_count > 1 and (word or "").strip().lower().endswith("o"):
        nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
        if nuclei and _vowel_stress(phonemes[nuclei[-1]]) != "1":
            phonemes = list(phonemes)
            phonemes[nuclei[-1]] = _base_code(phonemes[nuclei[-1]]) + "9"

    # Multi-syllable words ending in -ence or -ent (sentence, different, president)
    # -> the last syllable is unstressed -> set its vowel's stress digit to 9.
    # Guard: skip when the final vowel already has PRIMARY stress 1 (e.g. cement,
    # event, percent), where the last syllable really is stressed.
    if word and syllable_count and syllable_count > 1 and (word or "").strip().lower().endswith(("ence", "ent")):
        nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
        if nuclei and _vowel_stress(phonemes[nuclei[-1]]) != "1":
            phonemes = list(phonemes)
            phonemes[nuclei[-1]] = _base_code(phonemes[nuclei[-1]]) + "9"

    # Words ending in -cy, -ty, -phy, -gy, -al take stress on the antepenultimate
    # (3rd-from-last) syllable, so the LAST syllable is unstressed -> set its
    # vowel's stress digit to 9. Needs >= 3 syllables (so 2-syllable city/duty/final
    # are skipped). Guard: skip when the final vowel already has PRIMARY stress 1.
    if word and syllable_count and syllable_count >= 3 and (word or "").strip().lower().endswith(("cy", "ty", "phy", "gy", "al")):
        nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
        if nuclei and _vowel_stress(phonemes[nuclei[-1]]) != "1":
            phonemes = list(phonemes)
            phonemes[nuclei[-1]] = _base_code(phonemes[nuclei[-1]]) + "9"

    # A consonant + "Y" + "UW1" (the /ju:/ glide: cute K Y UW1 T, computer
    # ...P Y UW1..., music M Y UW1 ...) renders as Vietnamese "íu": make the "Y"
    # the stressed vowel (IY1) and demote "UW1" to unstressed (UW0), so the accent
    # lands on the "i" (otherwise you'd get "iú").
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

    # In a MULTI-syllable word the one remaining stress "1" is the word's PRIMARY
    # stress, which the two downgrade rules below must not strip (doing so left words
    # like continue / remember / concentrate with no stressed syllable). So those
    # rules only demote the vowel for a single-syllable word; a polysyllable keeps
    # its primary stress.
    _multi = syllable_count is not None and syllable_count >= 2

    # Within a syllable, a vowel/diphthong directly before a coda "M", "N" or "L"
    # is unstressed in this scheme -> change its primary stress 1 to 0, e.g.
    # time -> T AY0 M, file -> F AY0 L, film -> F IH0 L M. "Coda" means the M/N/L
    # is NOT the onset of a following vowel (so it must not be immediately followed
    # by a vowel) -- that spares "timer"/"funny" (M/N is an onset there). Only
    # touches stress 1, leaving the 9-markers set above intact. Runs after the 1/9
    # rule so the downgraded vowel isn't re-stressed. SKIPPED for polysyllables so a
    # primary-stressed syllable (continue's "tin", remember's "mem") isn't demoted.
    if not _multi:
        for i in range(len(phonemes) - 1):
            if phonemes[i][-1:] == "1" and phonemes[i + 1] in ("M", "N", "L"):
                after = phonemes[i + 2] if i + 2 < len(phonemes) else None
                if after is None or not after[-1:].isdigit():   # coda, not an onset
                    phonemes[i] = phonemes[i][:-1] + "0"

    # A stressed vowel/diphthong directly before an "ER" -> reduce the "ER" to "9",
    # and downgrade the vowel's stress 1 to 0 ONLY when that vowel is the word's
    # FIRST nucleus (the "monosyllabic-feel" vowel+ER words: fire "F AY1 ER0" ->
    # "F AY0 ER9", tire, liar, hour). When a syllable precedes it the vowel is the
    # real primary stress, so it is kept while the ER still reduces: desire
    # "D IH0 Z AY1 ER0" -> "...AY1 ER9".
    for i in range(len(phonemes) - 1):
        if phonemes[i][-1:] == "1" and phonemes[i + 1].startswith("ER"):
            vowel_is_first = not any(_vowel_stress(p) is not None for p in phonemes[:i])
            if vowel_is_first:
                phonemes[i] = phonemes[i][:-1] + "0"
            phonemes[i + 1] = phonemes[i + 1][:-1] + "9"

    return phonemes


def modify_arpabet_quality(phonemes, part_of_speech=None, syllable_count=None, word=None, hyphenated=None, flap_t=True):
    """Phoneme-QUALITY ARPAbet adjustments (runs BEFORE modify_arpabet_stress).
    Mostly changes base codes (vowels, and the T-flapping consonant rule) and
    leaves stress digits to modify_arpabet_stress, which runs afterwards -- the one
    exception is the word-final "AH0 L" rule below, which sets the reduced "AO9"
    directly. `hyphenated` is the per-POS corrected (Moby) hyphenation, e.g.
    "pres-ent", so rules can key off the spelled syllables.

    Rule -- consonant + "-le" final syllable: when the word's last spelled
    syllable is a consonant followed by "le" (ble, ple, cle, tle, dle, ...), as in
    "ta-ble", "ap-ple", "lit-tle", "ex-am-ple", that syllable's vowel takes the
    base code "AO" (keeping its existing digit for now, e.g. "AH0" -> "AO0"). The
    later modify_arpabet_stress pass applies the 1/9 rule with no exceptions, so
    this unstressed "-le" syllable ends up "AO9" (a falling-tone "ồ").

    Rule -- reduced "-age"/"-edge" word (AGE_EDGE_REDUCED_WORDS, e.g. "message",
    "knowledge"): the final syllable's vowel takes the base code "AF" (keeping its
    digit; modify_arpabet_stress then stamps the digit "8", giving "AF8").
    """
    if hyphenated is None and word is not None:
        hyphenated = corrected_hyphenation_for_pos(word, part_of_speech)

    # T-flapping / alveolar tap. A "T" becomes a "D" (-> Vietnamese "đ") when it
    # sits between two vowel sounds AND the following vowel is unstressed:
    #   - preceding phoneme is a vowel OR "R" (the r sound counts as a vowel here),
    #   - following phoneme is an unstressed vowel (cmudict stress digit 0 or 2).
    # e.g. water (AO1 T ER0) -> wa-der, party (R T IY0) -> par-dy. Runs first, on
    # the raw cmudict phonemes, so it reads the ORIGINAL stress (before the stress
    # pass rewrites unstressed vowels to the custom 9).
    phonemes = list(phonemes)
    # flap_t=False produces the STANDARD (dictionary) form, keeping every "T" as a
    # "t"; flap_t=True (default) applies American T-flapping (T -> D between vowels).
    if flap_t:
        for i in range(1, len(phonemes) - 1):
            if phonemes[i] == "T":
                prev = phonemes[i - 1]
                nxt = phonemes[i + 1]
                prev_is_vowel_sound = prev[-1:].isdigit() or prev == "R"
                next_is_unstressed_vowel = nxt[-1:] in ("0", "2")  # stress 0 or secondary 2
                if prev_is_vowel_sound and next_is_unstressed_vowel:
                    phonemes[i] = "D"

    nuclei = [i for i, p in enumerate(phonemes) if _vowel_stress(p) is not None]
    if _ends_in_consonant_le(hyphenated):
        # Change the LAST vowel nucleus (the "-le" syllable's vowel) to AO,
        # preserving its stress digit (strict split: no digit changes here).
        if nuclei:
            phonemes = list(phonemes)
            i = nuclei[-1]
            phonemes[i] = "AO" + _vowel_stress(phonemes[i])
    elif (word or "").strip().lower() in AGE_EDGE_REDUCED_WORDS:
        # Reduced "-age"/"-edge" (/ɪdʒ/): the LAST vowel nucleus takes base code
        # "AF", preserving its digit (the stress pass sets it to 8).
        if nuclei:
            phonemes = list(phonemes)
            i = nuclei[-1]
            phonemes[i] = "AF" + _vowel_stress(phonemes[i])

    # Word-final "...AH0 L" (lethal, mammal, animal, national): the final AH0
    # becomes the reduced custom code "AO9" ("ồ"). Consonant+"-le" words were
    # already handled above (their final vowel is now "AO0", not "AH0"), so they
    # don't match here. This one sets the digit directly (there's no later -al
    # stress rule), so it works for any syllable count.
    if phonemes[-2:] == ["AH0", "L"]:
        phonemes = phonemes[:-2] + ["AO9", "L"]

    return phonemes
