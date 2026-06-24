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

def synthesize_azure_audio(text, blob_name=None, language='en', slow=False):
    """Synthesize text to speech and upload to Azure Blob. Returns blob URL or None on failure."""
    print(f"Starting audio synthesis for text: '{text}' in language '{language}' with slow={slow}")
    if blob_name is None:
        blob_name = f"fr_{text}" if language != 'en' else text
    if slow:
        blob_name = f"slow_{blob_name }"
    voice_name = VOICE_MAP.get(language, 'en-US-JennyNeural')
    full_blob_name = f"{blob_name}.mp3"

    print(f"Generating audio for text: '{text}' with voice '{voice_name}' and blob name '{full_blob_name}'")
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

    if slow:
        ssml = (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{language}">'
            f'<voice name="{voice_name}">'
            f'<prosody rate="slow">{text}</prosody>'
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

# 1. Provide the base name (no extension) 
# Example: if your file is 'eng-vie.ifo', use 'eng-vie'
DICT_BASE_NAME = "en_vi" 

def read_viet_dict(word):
    if not os.path.exists(f"{DICT_BASE_NAME}.ifo"):
        print(f"Error: Could not find {DICT_BASE_NAME}.ifo in the current folder.")
        return

    print(f"--- Loading {DICT_BASE_NAME} ---")
    sd_dict = Dictionary(DICT_BASE_NAME)
    
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
                #print(f" ************** Found new part of speech: {part_of_speech}")
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
