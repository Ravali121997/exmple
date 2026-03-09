from langchain_google_genai import ChatGoogleGenerativeAI
import google.generativeai as genai
from app.models.base import DashboardContent,JobDescription
from app.core.Config import logger, GOOGLE_API_KEY, MODEL_TEMPERATURE
from fastapi import HTTPException, UploadFile, File
from app.database.mongo_connection import insert_data, find_one, update_one
from pydantic import BaseModel
from app.services.job_description.prompt_engineering import JobAnalysisPrompts
from typing import Optional, List, Dict, Union, Any, Tuple
from sqlalchemy.orm import Session
from app.services.gemini_model_loader import GeminiModelLoader
import io,os,json,random
import fitz
import docx
import re
import wave
import pyaudio
import sounddevice as sd
import threading
import speech_recognition as sr
import queue
import time
from datetime import datetime
from gtts import gTTS
from collections import defaultdict
from app.core.Config import JD_STORAGE
from app.services.job_description.prompt_engineering import (
    JobAnalysisPrompts,
    GENERATE_QA_PROMPT,
    GENERATE_SIMILAR_QA_PROMPT,
    EVALUATE_QA_PROMPT,
    QUESTION_STARTERS,
)

def clean_response(text: str) -> str:
    # Remove markdown code block wrappers
    if text.startswith("```json"):
        text = text[len("```json"):].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    # Remove control chars and normalize whitespace
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

class JDLLMService:
    def __init__(self):
        """Initialize Gemini + LangChain models using global config."""
        if not GOOGLE_API_KEY:
            raise ValueError("❌ GOOGLE_API_KEY is not set in configuration.")

        # Configure Gemini SDK with API key
        genai.configure(api_key=GOOGLE_API_KEY)

        # Initialize models
        self.gemini_model = GeminiModelLoader.get_model()
        self.langchain_model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=GOOGLE_API_KEY,
            temperature=MODEL_TEMPERATURE
        )
        
    @staticmethod
    def parse_llm_response(response_text: str) -> dict:
        """Parses Gemini output into structured dictionary."""
        fields = [
            "JOB_TITLE", "DEPARTMENT", "REQUIRED_SKILLS",
            "EXPERIENCE", "EDUCATION", "ROLE_DESCRIPTION",
            "EMPLOYMENT_TYPE", "KEYWORDS", "EXPERIENCE_LEVEL"
        ]
        result = {}
        for f in fields:
            match = re.search(rf"{f}:\s*(.*)", response_text or "", re.IGNORECASE)
            result[f] = match.group(1).strip() if match else None
        return result
    
    async def analyze_job_description(self, text: str) -> str:
        """Calls Gemini API to analyze job description text."""
        try:
            prompt = JobAnalysisPrompts.ANALYSIS_TEMPLATE.format(context=text)
            response = await self.gemini_model.generate_content_async(prompt)            
            if not response or not getattr(response, "text", None):
                logger.warning("Gemini returned empty response.")
                raise HTTPException(status_code=502, detail="Empty response from Gemini.")

            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise HTTPException(status_code=500, detail=f"Gemini API failed: {e}")
          
    async def generate_dashboard_prompt(self, meta_prompt: str) -> list[str]:
        """Generate dashboard prompts from structured JD data."""
        response = await self.gemini_model.generate_content_async(meta_prompt)
        raw_output = response.text.strip() if hasattr(response, "text") else str(response).strip()

        # Clean JSON wrapper if present
        if raw_output.startswith("```json"):
            raw_output = raw_output[len("```json"):].strip()
        if raw_output.endswith("```"):
            raw_output = raw_output[:-3].strip()

        try:
            result = json.loads(raw_output)
            return result if isinstance(result, list) else [raw_output]
        except Exception:
            return [raw_output]
    
    async def generate_sample_prompts(jd: JobDescription, num_prompts: int = 5):
        """
        Generate dynamic dashboard prompts from stored JD data (keywords + required skills).
        Produces one prompt per keyword/skill.
        """
        # Collect keywords and required skills
        raw_keywords = []
        if jd.keywords:
            raw_keywords += [kw.strip() for kw in jd.keywords.split(",")]
        if jd.required_skills:
            raw_keywords += [kw.strip() for kw in jd.required_skills.split(",")]

        # Deduplicate, clean, and shuffle
        keywords = list(set(kw for kw in raw_keywords if len(kw) > 2))
        random.shuffle(keywords)

        # Limit number of prompts
        keywords_for_prompts = keywords[:num_prompts] if len(keywords) >= num_prompts else keywords
        
        # ✅ Check for empty keywords and provide a generic fallback
        if not keywords_for_prompts:
            logger.warning("⚠️ No keywords found, using generic fallback prompts.")
            keywords_for_prompts = ["general professional skills"]
        # Initialize LLM service once
        llm_service = JDLLMService()
        prompts = []
        llm_used = False

        for kw in keywords_for_prompts:
            meta_prompt = JobAnalysisPrompts.DASHBOARD_PROMPT_GENERATOR.format(
                keywords=kw,
                num_prompts=1  # One prompt per keyword
            )

            try:
                result_list = await llm_service.generate_dashboard_prompt(meta_prompt)
                prompts.append(result_list[0]) 
                llm_used = True
            except Exception as e:
                logger.warning(f"LLM generation failed for keyword '{kw}': {e}", exc_info=True)
                # Fallback prompt
                prompts.append(f"Create a dashboard showing performance metrics for {kw}.")

        if llm_used:
            logger.info("✅ LLM successfully generated prompts.")
        else:
            logger.warning("⚠️ Fallback prompts used for all keywords.")

        return prompts



class DocumentProcessor:
    
    def __init__(self):
        self.interviewer_lines = []
        self.candidate_lines = []
        self.status = "success"
        self.data = None
        self.error = None
        self.model = GeminiModelLoader.get_model()

   
    def get_dashboard_prompt(jd_id: str, jd_text: str, dashboard_type: str = "custom", custom_prompt: str = None):
        """
        Build the full AI prompt for dashboard generation using the JD and optional user prompt.
        """
        if dashboard_type not in {"custom", "modified"}:
            dashboard_type = "custom"

        prompt = JobAnalysisPrompts.CUSTOM_DASHBOARD_PROMPT
        prompt += f"\n\n# JD ID: {jd_id}\n# Dashboard Type: {dashboard_type}\n# JD Text:\n{jd_text.strip()}\n"

        if custom_prompt:
            prompt += f"# Custom Prompt: {custom_prompt.strip()}\n"

        return prompt
    
    @staticmethod
    def parse_content(content):
        """Safely parse JSON content or return dict."""
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.warning("Failed to parse dashboard content JSON.")
                return {}
        return content or {}
    
    @staticmethod
    def extract_json_from_text(text: str) -> dict | None:        
        try:
            # Extract JSON block from the text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return None
            json_str = match.group()
            return json.loads(json_str)
        except Exception as e:
            logger.warning(f"Failed to parse JSON from LLM output: {e}")
            return None
        
    
    def generate_dashboard(
        self,
        jd_id: str,
        jd_text: str,
        dashboard_type: str = "custom",
        custom_prompt: str = None,
        base_dashboard_content: str = None,
    ) -> str:
        try:
            full_prompt = DocumentProcessor.get_dashboard_prompt(
                jd_id=jd_id,
                jd_text=jd_text,
                dashboard_type=dashboard_type,
                custom_prompt=custom_prompt,
            )

            if dashboard_type == "modified" and base_dashboard_content:
                full_prompt += f"\n\n# Existing Dashboard Content:\n{base_dashboard_content}\n"

            if custom_prompt is None:
                skills_data = JDAnalyzer.extract_skills_and_experience(jd_text)
                full_prompt += (
                    f"\n\n# Extracted Info:\n"
                    f"Technical Skills: {', '.join(skills_data['technical_skills'])}\n"
                    f"Soft Skills: {', '.join(skills_data['soft_skills'])}\n"
                    f"Experience Level: {skills_data['experience_level']}\n"
                )

            response = self.model.generate_content(full_prompt)
            #raw_output = response.text.strip()
            raw_output = clean_response(response.text.strip())


            # Attempt to parse JSON from output (optional)
            parsed_json = DocumentProcessor.extract_json_from_text(raw_output)

            if parsed_json:
                # Return pretty JSON string or just raw text as fallback
                return json.dumps(parsed_json, indent=2)
            else:
                logger.warning("Generated content was not valid JSON. Returning raw text.")
                return raw_output

        except Exception as e:
            logger.error(f"Error generating dashboard: {e}")
            return f"Error generating dashboard: {e}"

    
    def generate_multiple_dashboards_from_jd(self,jd_text: str, count: int = 1) -> list[dict]:
        """
        Generates multiple auto dashboards from a JD using LLM and the AUTO_DASHBOARD_PROMPT_TEMPLATE.

        Args:
            jd_text (str): The raw text of the job description.
            count (int): Number of dashboards to generate (1–10).

        Returns:
            list[dict]: A list of valid dashboards in the expected format.
        """
       
        def filter_valid_dashboards(dashboards):
            valid = []
            for d in dashboards:
                if (
                    isinstance(d, dict)
                    and d.get("dashboard_type") == "auto"
                    and isinstance(d.get("dashboard_title"), str)
                    and isinstance(d.get("overview"), list)
                    and all(isinstance(bp, str) for bp in d["overview"])
                ):
                    valid.append(d)
                else:
                    logger.warning(f"Invalid dashboard entry skipped: {d}")
            return valid

        try:
            prompt = JobAnalysisPrompts.DASHBOARD_AUTOGEN_PROMPT.format(
                jd_text=jd_text,
                count=count
            )

            response = self.model.generate_content(prompt)
            #raw_output = response.text.strip()
            raw_output = clean_response(response.text.strip())

            # Attempt to parse the entire response as JSON
            try:
                dashboards = json.loads(raw_output)
                if not isinstance(dashboards, list):
                    logger.warning("LLM returned JSON but not a list. Returning empty list.")
                    return []
                
                # Filter invalid dashboard entries
                dashboards = filter_valid_dashboards(dashboards)
                return dashboards

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse dashboard list JSON: {e}")
                logger.warning(f"Raw LLM output: {raw_output}")
                return []

        except Exception as e:
            logger.error(f"Error generating multiple dashboards: {e}")
            return []

   
    def generate_qa(dashboard_content: str, num_qa: int) -> str:
        try:
            qa_prompt = GENERATE_QA_PROMPT.format(
                num_qa=num_qa, dashboard_content=dashboard_content
            )
            generate_qa_response = DocumentProcessor.model.generate_content(qa_prompt)
            qa_text = generate_qa_response.text.strip()

            formatted_qa = []
            lines = qa_text.split("\n")
            current_qa_pair = []

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if line.startswith("Q"):
                    if current_qa_pair:
                        formatted_qa.extend(current_qa_pair)
                        current_qa_pair = []
                    line = re.sub(r"^Q\s*(\d+)\s*:", r"Q\1:", line)
                    current_qa_pair.append(line)

                elif line.startswith("A"):
                    line = re.sub(r"^A\s*(\d+)\s*:", r"A\1:", line)
                    current_qa_pair.append(line)

            if current_qa_pair:
                formatted_qa.extend(current_qa_pair)

            return "\n".join(formatted_qa)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error generating Q&A: {str(e)}"
            )


class TranscriptionState(BaseModel):
    is_recording: bool = False
    interviewer_lines: List[str] = []
    candidate_lines: List[str] = []
    current_question_id: int = 0
    last_answer_time: float = 0


class TranscriberResponse(BaseModel):
    status: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class GenerateQARequest(BaseModel):
    num_pairs: int


class InitializeRequest(BaseModel):
    api_key: str

class DualInputTranscriber:
    _instance = None
    _state = TranscriptionState()
    model = None
    is_recording = False
    is_initialized = False
    api_key = 'AIzaSyB3ZN_ICuWtHUypL1vhvORWA7KwoNiKVMw'
    conversation_history = defaultdict(list)
    session_data = {}  # Add this line to store session data

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DualInputTranscriber, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            self.recognizer = sr.Recognizer()
            self.audio = pyaudio.PyAudio()
            self.mic_queue = queue.Queue()
            self.speaker_queue = queue.Queue()
            self.text_queue = queue.Queue()
            self.initialized = True
            print("DualInputTranscriber initialized")
    
    @classmethod
    async def record_single_input(cls, role, session_id, action):
        """
        Record a single input (either interviewer or candidate) and return the transcribed text.
        
        Args:
            role: Either "interviewer" or "candidate"
            session_id: Session identifier
            action: "start" to begin recording or "stop" to stop recording
        
        Returns:
            Dictionary with status and transcription results
        """
        try:
            # Initialize if not already done
            if not cls.is_initialized:
                api_key = 'AIzaSyB3ZN_ICuWtHUypL1vhvORWA7KwoNiKVMw'
                genai.configure(api_key=api_key)
                cls.model = GeminiModelLoader.get_model()
                cls.is_initialized = True
            
            # Initialize session data if not exists
            if not hasattr(cls, 'session_data'):
                cls.session_data = {}
                
            if session_id not in cls.session_data:
                cls.session_data[session_id] = {
                    "interviewer_lines": [],
                    "candidate_lines": [],
                    "recording_state": {},
                    "current_recording": None,
                    "audio_data": None
                }
            
            session = cls.session_data[session_id]
            
            if action == "start":
                # Start a new recording thread
                if not hasattr(cls, 'recognizer'):
                    cls.recognizer = sr.Recognizer()
                
                # Set recording state
                session["current_recording"] = {
                    "role": role,
                    "start_time": time.time(),
                    "is_recording": True
                }
                
                # Start recording in a separate thread to not block the API
                import threading
                
                def record_audio():
                    try:
                        with sr.Microphone() as source:
                            logger.info(f"Adjusting for ambient noise for {role}...")
                            cls.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                            
                            logger.info(f"Started recording for {role}. Waiting for speech...")
                            # Set a longer timeout and phrase_time_limit
                            audio = cls.recognizer.listen(source, timeout=None, phrase_time_limit=None)
                            
                            # Store the audio data in the session
                            session["audio_data"] = audio
                            logger.info(f"Audio captured for {role} and stored in session")
                    except Exception as e:
                        logger.error(f"Error in recording thread: {e}")
                        session["current_recording"]["is_recording"] = False
                
                # Start recording thread
                recording_thread = threading.Thread(target=record_audio)
                recording_thread.daemon = True
                recording_thread.start()
                
                logger.info(f"Started recording thread for {role} in session {session_id}")
                
                return {
                    "status": "success",
                    "data": {
                        "message": f"Started recording for {role}",
                        "role": role,
                        "session_id": session_id
                    }
                }
                
            elif action == "stop":
                # Check if recording is active
                if not session.get("current_recording") or not session["current_recording"].get("is_recording"):
                    logger.warning(f"Not recording for {session_id}. Cannot stop a non-existent recording.")
                    return {
                        "status": "error",
                        "error": "No active recording to stop."
                    }
                
                # Set recording state to stopped
                session["current_recording"]["is_recording"] = False
                
                # Process the audio data
                try:
                    # Check if we have audio data
                    if not session.get("audio_data"):
                        logger.warning(f"No audio data found for {role} in session {session_id}")
                        return {
                            "status": "error",
                            "error": "No audio data captured. Please try again."
                        }
                    
                    # Process the audio data
                    audio = session["audio_data"]
                    
                    logger.info(f"Processing audio data for {role}...")
                    text = cls.recognizer.recognize_google(audio)
                    
                    # Define remove_repeated_words function inline
                    def remove_repeated_words(input_text):
                        words = input_text.split()
                        if not words:
                            return ""
                        cleaned_words = [words[0]]
                        for i in range(1, len(words)):
                            if words[i].lower() != words[i - 1].lower():
                                cleaned_words.append(words[i])
                        return " ".join(cleaned_words)
                    
                    # Use the inline function
                    text = remove_repeated_words(text)
                    
                    logger.info(f"Transcribed text for {role}: {text}")
                    
                    # Store the transcribed text
                    if role == "interviewer":
                        session["interviewer_lines"].append(text)
                    else:
                        session["candidate_lines"].append(text)
                    
                    # Create combined transcript
                    combined_transcript = ""
                    for i, question in enumerate(session["interviewer_lines"]):
                        combined_transcript += f"Interviewer: {question}\n"
                        if i < len(session["candidate_lines"]):
                            combined_transcript += f"Candidate: {session['candidate_lines'][i]}\n"
                    
                    # Create MongoDB document if it doesn't exist
                    from datetime import datetime  # Make sure to import datetime correctly
                    current_time = datetime.now()  # Use datetime.now() correctly
                    
                    active_recording = find_one(
                        "interview_transcriptions",
                        {"status": "Active", "interview_type": "job_description", "session_id": session_id}
                    )
                    
                    if not active_recording:
                        # Create new recording document
                        recording_data = {
                            "status": "Active",
                            "speaker_type": "dual",
                            "transcript_text": combined_transcript,
                            "interviewer_text": "\n".join(session["interviewer_lines"]),
                            "candidate_text": "\n".join(session["candidate_lines"]),
                            "created_at": current_time,  # Use current_time instead of datetime.now()
                            "interview_type": "job_description",
                            "session_id": session_id,
                            "speaker_segments": [],
                            "questions_and_answers": []
                        }
                        
                        # Insert into MongoDB
                        result = insert_data("interview_transcriptions", recording_data)
                        recording_id = str(result.inserted_id)
                        logger.info(f"Created new recording document with ID: {recording_id}")
                    else:
                        # Update existing document
                        recording_id = str(active_recording["_id"])
                        
                        # Create Q&A pairs
                        qa_pairs = []
                        for i, question in enumerate(session["interviewer_lines"]):
                            qa_pair = {
                                "question": question,
                                "answer": session["candidate_lines"][i] if i < len(session["candidate_lines"]) else ""
                            }
                            qa_pairs.append(qa_pair)
                        
                        # Update MongoDB
                        update_one(
                            "interview_transcriptions",
                            {"_id": active_recording["_id"]},
                            {
                                "$set": {
                                    "transcript_text": combined_transcript,
                                    "interviewer_text": "\n".join(session["interviewer_lines"]),
                                    "candidate_text": "\n".join(session["candidate_lines"]),
                                    "updated_at": current_time,  # Use current_time instead of datetime.now()
                                    "speaker_segments": [
                                        {"speaker": "interviewer", "text": text} 
                                        for text in session["interviewer_lines"]
                                    ] + [
                                        {"speaker": "candidate", "text": text}
                                        for text in session["candidate_lines"]
                                    ],
                                    "questions_and_answers": qa_pairs
                                }
                            }
                        )
                        logger.info(f"Updated recording document with ID: {recording_id}")
                    
                    # Generate audio response if needed
                    audio_response = None
                    try:
                        from gtts import gTTS
                        import os
                        
                        # Create temp directory if it doesn't exist
                        temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "temp")
                        os.makedirs(temp_dir, exist_ok=True)
                        
                        # Generate a unique filename
                        audio_file = os.path.join(temp_dir, f"response_{int(time.time())}.mp3")
                        
                        # Generate and save audio
                        tts = gTTS(text, lang="en")
                        tts.save(audio_file)
                        
                        audio_response = audio_file
                        logger.info(f"Generated audio response: {audio_file}")
                    except Exception as e:
                        logger.error(f"Error generating audio response: {e}")
                    
                    # Clear audio data but keep recording state for reference
                    session["audio_data"] = None
                    
                    return {
                        "status": "success",
                        "data": {
                            "text": text,
                            "role": role,
                            "session_id": session_id,
                            "recording_id": recording_id,
                            "transcript": combined_transcript,
                            "audio_response": audio_response
                        }
                    }
                    
                except sr.UnknownValueError:
                    logger.error("Speech recognition could not understand audio")
                    session["audio_data"] = None
                    return {
                        "status": "error", 
                        "error": "Could not understand audio. Please speak clearly and try again."
                    }
                    
                except sr.RequestError as e:
                    logger.error(f"Could not request results from Google Speech Recognition service: {e}")
                    session["audio_data"] = None
                    return {
                        "status": "error", 
                        "error": f"Speech recognition service error: {e}"
                    }
                    
                except Exception as e:
                    logger.error(f"Error processing audio: {e}")
                    session["audio_data"] = None
                    return {
                        "status": "error", 
                        "error": "Failed to record audio. Please check your microphone and try again.",
                        "details": str(e)
                    }
            
            else:
                return {"status": "error", "error": f"Unknown action: {action}"}
                
        except Exception as e:
            logger.error(f"Error in record_single_input: {e}")
            # Make sure to clear the recording state in case of errors
            if 'session' in locals() and session:
                session["audio_data"] = None
            return {"status": "error", "error": str(e)}



        
    @classmethod
    async def get_conversation_history(cls, session_id):
        """
        Get the conversation history for a specific session.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Dictionary with status and conversation history
        """
        try:
            # Initialize session data if not exists
            if not hasattr(cls, 'session_data'):
                cls.session_data = {}
                
            # Check if session exists
            if session_id not in cls.session_data:
                return {
                    "status": "success",
                    "data": {
                        "history": "",
                        "interviewer_lines": [],
                        "candidate_lines": []
                    }
                }
            
            session = cls.session_data[session_id]
            
            # Create combined transcript
            combined_transcript = ""
            for i, question in enumerate(session["interviewer_lines"]):
                combined_transcript += f"Interviewer: {question}\n"
                if i < len(session["candidate_lines"]):
                    combined_transcript += f"Candidate: {session['candidate_lines'][i]}\n"
            
            return {
                "status": "success",
                "data": {
                    "history": combined_transcript,
                    "interviewer_lines": session["interviewer_lines"],
                    "candidate_lines": session["candidate_lines"]
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting conversation history: {e}")
            return {"status": "error", "error": str(e)}    
    def remove_repeated_words(self, text):
        """Remove immediately repeated words in text."""
        if not text:
            return text
            
        words = text.split()
        if len(words) <= 1:
            return text
            
        result = [words[0]]
        for i in range(1, len(words)):
            if words[i].lower() != words[i-1].lower():
                result.append(words[i])
                
        return ' '.join(result)
    
    @classmethod
    def recognize_speech_from_audio(cls, audio_file, role, session_id):
        """
        Convert audio input to text using speech recognition.
        
        Args:
            audio_file: Path to the audio file
            role: Either "interviewer" or "candidate"
            session_id: Session identifier
        
        Returns:
            Tuple of (text, conversation_history)
        """
        try:
            # Initialize recognizer if not already done
            if not hasattr(cls, 'recognizer'):
                cls.recognizer = sr.Recognizer()
            
            # Initialize conversation history if not exists
            if not hasattr(cls, 'conversation_history'):
                cls.conversation_history = defaultdict(list)
            
            with sr.AudioFile(audio_file) as source:
                audio_data = cls.recognizer.record(source)
                text = cls.recognizer.recognize_google(audio_data)
                text = cls.remove_repeated_words(text)
                
                # Store in conversation history
                cls.conversation_history[session_id].append(f"{role}: {text}")
                
                # Limit history to last 20 exchanges
                if len(cls.conversation_history[session_id]) > 20:
                    cls.conversation_history[session_id] = cls.conversation_history[session_id][-20:]
                
                return text, "\n".join(cls.conversation_history[session_id])
        except sr.UnknownValueError:
            return "⚠️ Could not understand audio.", "\n".join(cls.conversation_history.get(session_id, []))
        except sr.RequestError as e:
            return f"⚠️ Speech recognition error: {str(e)}", "\n".join(cls.conversation_history.get(session_id, []))
        except Exception as e:
            return f"⚠️ Error: {str(e)}", "\n".join(cls.conversation_history.get(session_id, []))

    @classmethod
    def generate_audio_response(cls, text):
        """
        Generate audio from text.
        
        Args:
            text: Input text
        
        Returns:
            Path to the generated audio file
        """
        try:
            from gtts import gTTS
            import io
            import os
            
            tts = gTTS(text, lang="en")
            audio_buffer = io.BytesIO()
            tts.write_to_fp(audio_buffer)
            audio_buffer.seek(0)
            
            # Save to a temporary file
            temp_file = "temp_audio.mp3"
            with open(temp_file, "wb") as f:
                f.write(audio_buffer.getvalue())
            
            return temp_file
        except Exception as e:
            logger.error(f"Audio generation error: {str(e)}")
            return f"⚠️ Audio generation error: {str(e)}"
    
    def _transcribe_mic(self):
        """Transcribe from microphone (interviewer) with improved error handling."""
        while DualInputTranscriber.is_recording:
            try:
                with sr.Microphone() as source:
                    print("Adjusting for ambient noise...")
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    print("Listening to microphone...")
                    try:
                        audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
                        text = self.recognizer.recognize_google(audio)
                        if text:
                            # Clean up repeated words
                            text = self.remove_repeated_words(text)
                            print("Mic transcribed:", text)

                            # Add to conversation history
                            session_id = "default"
                            DualInputTranscriber.conversation_history[session_id].append(f"Interviewer: {text}")

                            # Add directly to the state - this is critical
                            DualInputTranscriber._state.interviewer_lines.append(text)

                            # Also add to the queue for processing
                            self.mic_queue.put(text)

                            # Immediately update MongoDB
                            self._update_mongodb_now()

                            # Print confirmation
                            print(f"Added interviewer text: {text}")
                            print(f"Current interviewer lines: {DualInputTranscriber._state.interviewer_lines}")
                    except sr.WaitTimeoutError:
                        print("No speech detected")
                    except sr.UnknownValueError:
                        print("Speech not understood")
                    except sr.RequestError as e:
                        print(f"Could not request results; {str(e)}")

                # Add a small delay to prevent CPU overuse
                time.sleep(0.5)
            except Exception as e:
                print(f"Microphone transcription error: {str(e)}")
                time.sleep(1)

    def _transcribe_candidate_mic(self):
        """Directly transcribe candidate responses using the microphone with improved error handling."""
        while DualInputTranscriber.is_recording:
            try:
                # Wait a bit to let the interviewer finish speaking
                time.sleep(1)

                # Check if we have more interviewer lines than candidate lines
                if len(DualInputTranscriber._state.interviewer_lines) > len(DualInputTranscriber._state.candidate_lines):
                    print("Waiting for candidate response...")

                    with sr.Microphone() as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        print("Listening for candidate response...")
                        try:
                            # Use a longer timeout for candidate responses
                            audio = self.recognizer.listen(source, timeout=10, phrase_time_limit=30)
                            text = self.recognizer.recognize_google(audio)
                            if text:
                                # Clean up repeated words
                                text = self.remove_repeated_words(text)
                                print("Candidate response captured:", text)
                                
                                # Add to conversation history
                                session_id = "default"
                                DualInputTranscriber.conversation_history[session_id].append(f"Candidate: {text}")
                                
                                # Add to candidate lines - this is critical
                                DualInputTranscriber._state.candidate_lines.append(text)
                                
                                # Also add to the queue for processing
                                self.speaker_queue.put(text)
                                
                                # Immediately update MongoDB
                                self._update_mongodb_now()
                        except sr.WaitTimeoutError:
                            print("No candidate response detected")
                        except sr.UnknownValueError:
                            print("Candidate response not understood")
                        except sr.RequestError as e:
                            print(f"Could not request results for candidate; {str(e)}")
            
                # Add a small delay to prevent CPU overuse
                time.sleep(0.5)
            except Exception as e:
                print(f"Candidate mic transcription error: {str(e)}")
                time.sleep(1)

    def _transcribe_speaker(self):
        """Transcribe system audio with improved error handling"""
        RATE = 44100
        CHUNK = 1024 * 4

        while DualInputTranscriber.is_recording:
            try:
                # Find appropriate device
                device_id = self.find_loopback_device()
                if device_id is None:
                    print("\nNo loopback device found. Falling back to default microphone for candidate audio.")
                    # Use the default microphone as a fallback
                    with sr.Microphone() as source:
                        print("Adjusting for candidate microphone...")
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        print("Listening for candidate response...")
                        try:
                            audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=15)
                            text = self.recognizer.recognize_google(audio)
                            if text:
                                # Explicitly add to candidate_lines
                                DualInputTranscriber._state.candidate_lines.append(text)
                                print("Candidate said:", text)
                        except sr.WaitTimeoutError:
                            print("No candidate speech detected")
                        except sr.UnknownValueError:
                            print("Candidate speech not understood")
                        except sr.RequestError as e:
                            print(f"Could not request results for candidate; {str(e)}")
                    continue

                device_info = sd.query_devices(device_id)
                print(f"\nInitializing audio capture with device: {device_info['name']}")

                # Configure stream with device's native parameters
                stream = sd.RawInputStream(
                    device=device_id,
                    channels=1,  # Force mono
                    samplerate=int(device_info["default_samplerate"]),
                    blocksize=CHUNK,
                    dtype="int16",
                )

                with stream:
                    print("Successfully started audio capture stream for candidate")
                    while DualInputTranscriber.is_recording:
                        try:
                            raw_data, overflowed = stream.read(CHUNK)
                            if overflowed:
                                print("Audio buffer overflow detected")
                                continue

                            # Process audio data...
                            audio_bytes = io.BytesIO()
                            with wave.open(audio_bytes, "wb") as wav_file:
                                wav_file.setnchannels(1)
                                wav_file.setsampwidth(2)
                                wav_file.setframerate(RATE)
                                wav_file.writeframes(raw_data)

                            # Perform speech recognition
                            audio_bytes.seek(0)
                            audio = sr.AudioData(
                                audio_bytes.read(), sample_rate=RATE, sample_width=2
                            )

                            text = self.recognizer.recognize_google(audio)
                            if text:
                                # This is important - we're explicitly adding to candidate_lines
                                DualInputTranscriber._state.candidate_lines.append(text)
                                print("Candidate said:", text)
                        except sr.UnknownValueError:
                            pass  # No speech detected
                        except sr.RequestError as e:
                            print(f"Speech recognition service error: {str(e)}")
                        except Exception as e:
                            print(f"Error during audio processing: {str(e)}")

            except Exception as e:
                print(f"\nSpeaker transcription error: {str(e)}")
                print(f"Error type: {type(e).__name__}")
                print("Waiting before retry...")
                time.sleep(2)

    def find_loopback_device(self):
        """Find a suitable loopback device with improved detection"""
        try:
            devices = sd.query_devices()
            print("\nScanning available audio devices:")

            # Print all devices for debugging
            for i, device in enumerate(devices):
                print(f"\nDevice {i}: {device['name']}")
                print(f"  Input channels: {device['max_input_channels']}")
                print(f"  Output channels: {device['max_output_channels']}")
                print(f"  Default samplerate: {device['default_samplerate']}")
                print(f"  Is default input: {i == sd.default.device[0]}")
                print(f"  Is default output: {i == sd.default.device[1]}")

            # Strategy 1: Try to find a loopback device
            for i, device in enumerate(devices):
                if any(
                    name in device["name"].lower()
                    for name in ["loopback", "cable input", "virtual", "blackhole"]
                ):
                    print(f"\nFound loopback device: {device['name']}")
                    return i

            # Strategy 2: Try to use the default input device
            default_input = sd.default.device[0]
            if default_input is not None and default_input >= 0:
                device = devices[default_input]
                if device["max_input_channels"] > 0:
                    print(f"\nUsing default input device: {device['name']}")
                    return default_input


            # Strategy 3: Find any device with input capabilities
            for i, device in enumerate(devices):
                if device["max_input_channels"] > 0:
                    print(f"\nUsing first available input device: {device['name']}")
                    return i

            print("\nNo suitable audio device found!")
            return None

        except Exception as e:
            print(f"\nError while scanning audio devices: {str(e)}")
            return None

    def _update_mongodb_now(self):
        """Immediately update MongoDB with current state"""
        try:
            # Get the latest active recording
            active_recording = find_one(
                "interview_transcriptions",
                {"status": "Active", "interview_type": "job_description"}
            )

            if active_recording:
                # Combine interviewer and candidate lines
                interviewer_text = "\n".join(
                    DualInputTranscriber._state.interviewer_lines
                )
                candidate_text = "\n".join(
                    DualInputTranscriber._state.candidate_lines
                )

                # Create properly formatted transcript with clear speaker labels
                combined_transcript = ""
                for i, question in enumerate(
                    DualInputTranscriber._state.interviewer_lines
                ):
                    combined_transcript += f"Interviewer: {question}\n"
                    if i < len(DualInputTranscriber._state.candidate_lines):
                        combined_transcript += f"Candidate: {DualInputTranscriber._state.candidate_lines[i]}\n"

                # Create Q&A pairs
                qa_pairs = []
                for i, question in enumerate(DualInputTranscriber._state.interviewer_lines):
                    qa_pair = {
                        "question": question,
                        "answer": DualInputTranscriber._state.candidate_lines[i] if i < len(DualInputTranscriber._state.candidate_lines) else ""
                    }
                    qa_pairs.append(qa_pair)

                # Use datetime.now() correctly
                from datetime import datetime
                current_datetime = datetime.now()
                
                # Update the MongoDB document
                result = update_one(
                    "interview_transcriptions",
                    {"_id": active_recording["_id"]},
                    {
                        "$set": {
                            "transcript_text": combined_transcript,
                            "interviewer_text": interviewer_text,
                            "candidate_text": candidate_text,
                            "updated_at": current_datetime,
                            "speaker_segments": [
                                {"speaker": "interviewer", "text": text} 
                                for text in DualInputTranscriber._state.interviewer_lines
                            ] + [
                                {"speaker": "candidate", "text": text}
                                for text in DualInputTranscriber._state.candidate_lines
                            ],
                            "questions_and_answers": qa_pairs
                        }
                    },
                )

                print(f"Updated MongoDB document with {len(DualInputTranscriber._state.interviewer_lines)} interviewer lines and {len(DualInputTranscriber._state.candidate_lines)} candidate lines")
                print(f"MongoDB update result: {result}")
        except Exception as e:
            print(f"Error updating MongoDB document: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    def _update_mongodb_document(self):
        """Periodically update the MongoDB document with the current transcription"""
        last_update_time = time.time()
        
        # Import datetime correctly
        from datetime import datetime
        
        while DualInputTranscriber.is_recording:
            try:
                # Update every 2 seconds
                current_time = time.time()
                if current_time - last_update_time >= 2:
                    # Get the latest active recording
                    active_recording = find_one(
                        "interview_transcriptions",
                        {"status": "Active", "interview_type": "job_description"}
                    )

                    if active_recording:
                        # Combine interviewer and candidate lines
                        interviewer_text = "\n".join(
                            DualInputTranscriber._state.interviewer_lines
                        )
                        candidate_text = "\n".join(
                            DualInputTranscriber._state.candidate_lines
                        )

                        # Create properly formatted transcript with clear speaker labels
                        combined_transcript = ""
                        for i, question in enumerate(
                            DualInputTranscriber._state.interviewer_lines
                        ):
                            combined_transcript += f"Interviewer: {question}\n"
                            if i < len(DualInputTranscriber._state.candidate_lines):
                                combined_transcript += f"Candidate: {DualInputTranscriber._state.candidate_lines[i]}\n"

                        # Create Q&A pairs
                        qa_pairs = []
                        for i, question in enumerate(DualInputTranscriber._state.interviewer_lines):
                            qa_pair = {
                                "question": question,
                                "answer": DualInputTranscriber._state.candidate_lines[i] if i < len(DualInputTranscriber._state.candidate_lines) else ""
                            }
                            qa_pairs.append(qa_pair)

                        # Update the MongoDB document
                        update_one(
                            "interview_transcriptions",
                            {"_id": active_recording["_id"]},
                            {
                                "$set": {
                                    "transcript_text": combined_transcript,
                                    "interviewer_text": interviewer_text,
                                    "candidate_text": candidate_text,
                                    "updated_at": datetime.now(),
                                    "speaker_segments": [
                                        {"speaker": "interviewer", "text": text} 
                                        for text in DualInputTranscriber._state.interviewer_lines
                                    ] + [
                                        {"speaker": "candidate", "text": text}
                                        for text in DualInputTranscriber._state.candidate_lines
                                    ],
                                    "questions_and_answers": qa_pairs
                                }
                            },
                        )

                        print(f"Updated MongoDB document with {len(DualInputTranscriber._state.interviewer_lines)} interviewer lines and {len(DualInputTranscriber._state.candidate_lines)} candidate lines")

                    last_update_time = current_time

                time.sleep(0.5)  # Sleep to prevent high CPU usage

            except Exception as e:
                print(f"Error updating MongoDB document: {str(e)}")
                time.sleep(2)  # Wait longer on error
        

        @classmethod
        def _get_combined_text(cls) -> str:
            """Combine interviewer and candidate text with improved formatting"""
            combined_text = ["Interviewer:"]
            state = cls._state

            for i, question in enumerate(state.interviewer_lines):
                combined_text.append(question)
                if i < len(state.candidate_lines):
                    answer = state.candidate_lines[i]
                    if answer:
                        answer = answer.rstrip()
                        if not answer.endswith((".", "!", "?")):
                            answer += "."
                        combined_text.append(answer)

            return "\n".join(combined_text)

        @classmethod
        def get_evaluation_qa_content(cls, eval_id):
            """
            Retrieve evaluation content by evaluation ID
            
            Args:
                eval_id (str): The ID of the evaluation to retrieve
                
            Returns:
                dict: The evaluation data including question, answer, and evaluation results
            """
            try:
                # Find the evaluation in MongoDB
                evaluation = find_one("qa_evaluations", {"_id": eval_id})
                
                if not evaluation:
                    return {
                        "status": "error",
                        "error": f"Evaluation with ID {eval_id} not found"
                    }
                    
                # Return the evaluation data
                return {
                    "status": "success",
                    "evaluation": evaluation
                }
            except Exception as e:
                logger.error(f"Error retrieving evaluation: {str(e)}")
                return {
                    "status": "error",
                    "error": f"Error retrieving evaluation: {str(e)}"
                }

        @classmethod
        async def record_single_input(cls, role, session_id, action):
            """
            Record a single input (either interviewer or candidate) and return the transcribed text.
            
            Args:
                role: Either "interviewer" or "candidate"
                session_id: Session identifier
                action: "start" to begin recording or "stop" to stop recording
            
            Returns:
                Dictionary with status and transcription results
            """
            try:
                # Initialize if not already done
                if not cls.is_initialized:
                    api_key = 'AIzaSyB3ZN_ICuWtHUypL1vhvORWA7KwoNiKVMw'
                    genai.configure(api_key=api_key)
                    cls.model = GeminiModelLoader.get_model()
                    cls.is_initialized = True
                
                # Get or create instance
                instance = cls._instance or cls()
                
                # Initialize session data if not exists
                if session_id not in cls.session_data:
                    cls.session_data[session_id] = {
                        "interviewer_lines": [],
                        "candidate_lines": [],
                        "recording_state": {},
                        "current_recording": None
                    }
                
                session = cls.session_data[session_id]
                
                if action == "start":
                    # Start recording
                    if session.get("current_recording"):
                        return {"status": "error", "error": "Already recording"}
                    
                    # Create a recognizer
                    recognizer = sr.Recognizer()
                    
                    # Configure audio settings
                    sample_rate = 16000
                    duration = 10  # Record for up to 10 seconds
                    
                    # Start recording in a separate thread
                    session["current_recording"] = {
                        "role": role,
                        "start_time": time.time(),
                        "audio_data": [],
                        "recognizer": recognizer
                    }
                    
                    # Use PyAudio to record
                    p = pyaudio.PyAudio()
                    stream = p.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=sample_rate,
                        input=True,
                        frames_per_buffer=1024
                    )
                    
                    # Store stream in session
                    session["current_recording"]["stream"] = stream
                    session["current_recording"]["pyaudio"] = p
                    
                    logger.info(f"Started recording for {role} in session {session_id}")
                    
                    return {
                        "status": "success",
                        "data": {
                            "message": f"Started recording for {role}",
                            "role": role,
                            "session_id": session_id
                        }
                    }
                    
                elif action == "stop":
                    # Stop recording and process
                    if not session.get("current_recording"):
                        return {"status": "error", "error": "Not recording"}
                    
                    current_recording = session["current_recording"]
                    
                    # Stop the stream
                    if "stream" in current_recording:
                        current_recording["stream"].stop_stream()
                        current_recording["stream"].close()
                        current_recording["pyaudio"].terminate()
                    
                    # Process the audio data
                    try:
                        # Use speech recognition
                        recognizer = sr.Recognizer()
                        with sr.Microphone() as source:
                            audio = recognizer.listen(source, timeout=1)
                        
                        text = recognizer.recognize_google(audio)
                        logger.info(f"Transcribed text for {role}: {text}")
                        
                        # Store the transcribed text
                        if role == "interviewer":
                            session["interviewer_lines"].append(text)
                        else:
                            session["candidate_lines"].append(text)
                        
                        # Create combined transcript
                        combined_transcript = ""
                        for i, question in enumerate(session["interviewer_lines"]):
                            combined_transcript += f"Interviewer: {question}\n"
                            if i < len(session["candidate_lines"]):
                                combined_transcript += f"Candidate: {session['candidate_lines'][i]}\n"
                        
                        # Create MongoDB document if it doesn't exist
                        active_recording = find_one(
                            "interview_transcriptions",
                            {"status": "Active", "interview_type": "job_description", "session_id": session_id}
                        )
                        
                        if not active_recording:
                            # Create new recording document
                            recording_data = {
                                "status": "Active",
                                "speaker_type": "dual",
                                "transcript_text": combined_transcript,
                                "interviewer_text": "\n".join(session["interviewer_lines"]),
                                "candidate_text": "\n".join(session["candidate_lines"]),
                                "created_at": datetime.now(),
                                "interview_type": "job_description",
                                "session_id": session_id,
                                "speaker_segments": [],
                                "questions_and_answers": []
                            }
                            
                            # Insert into MongoDB
                            result = insert_data("interview_transcriptions", recording_data)
                            recording_id = str(result.inserted_id)
                            logger.info(f"Created new recording document with ID: {recording_id}")
                        else:
                            # Update existing document
                            recording_id = str(active_recording["_id"])
                            
                            # Create Q&A pairs
                            qa_pairs = []
                            for i, question in enumerate(session["interviewer_lines"]):
                                qa_pair = {
                                    "question": question,
                                    "answer": session["candidate_lines"][i] if i < len(session["candidate_lines"]) else ""
                                }
                                qa_pairs.append(qa_pair)
                            
                            # Update MongoDB
                            update_one(
                                "interview_transcriptions",
                                {"_id": active_recording["_id"]},
                                {
                                    "$set": {
                                        "transcript_text": combined_transcript,
                                        "interviewer_text": "\n".join(session["interviewer_lines"]),
                                        "candidate_text": "\n".join(session["candidate_lines"]),
                                        "updated_at": datetime.now(),
                                        "speaker_segments": [
                                            {"speaker": "interviewer", "text": text} 
                                            for text in session["interviewer_lines"]
                                        ] + [
                                            {"speaker": "candidate", "text": text}
                                            for text in session["candidate_lines"]
                                        ],
                                        "questions_and_answers": qa_pairs
                                    }
                                }
                            )
                            logger.info(f"Updated recording document with ID: {recording_id}")
                        
                        # Clear current recording
                        session["current_recording"] = None
                        
                        return {
                            "status": "success",
                            "data": {
                                "text": text,
                                "role": role,
                                "session_id": session_id,
                                "recording_id": recording_id,
                                "transcript": combined_transcript
                            }
                        }
                        
                    except sr.UnknownValueError:
                        logger.error("Speech recognition could not understand audio")
                        session["current_recording"] = None
                        return {"status": "error", "error": "Could not understand audio"}
                        
                    except sr.RequestError as e:
                        logger.error(f"Could not request results from Google Speech Recognition service: {e}")
                        session["current_recording"] = None
                        return {"status": "error", "error": f"Speech recognition service error: {e}"}
                        
                    except Exception as e:
                        logger.error(f"Error processing audio: {e}")
                        session["current_recording"] = None
                        return {"status": "error", "error": f"Error processing audio: {e}"}
                
                else:
                    return {"status": "error", "error": f"Unknown action: {action}"}
                    
            except Exception as e:
                logger.error(f"Error in record_single_input: {e}")
                return {"status": "error", "error": str(e)}

        @classmethod
        async def get_conversation_history(cls, session_id):
            """
            Get the conversation history for a specific session.
            
            Args:
                session_id: Session identifier
            
            Returns:
                Dictionary with status and conversation history
            """
            try:
                # Check if session exists
                if session_id not in cls.session_data:
                    return {
                        "status": "success",
                        "data": {
                            "history": "",
                            "interviewer_lines": [],
                            "candidate_lines": []
                        }
                    }
                
                session = cls.session_data[session_id]
                
                # Create combined transcript
                combined_transcript = ""
                for i, question in enumerate(session["interviewer_lines"]):
                    combined_transcript += f"Interviewer: {question}\n"
                    if i < len(session["candidate_lines"]):
                        combined_transcript += f"Candidate: {session['candidate_lines'][i]}\n"
                
                return {
                    "status": "success",
                    "data": {
                        "history": combined_transcript,
                        "interviewer_lines": session["interviewer_lines"],
                        "candidate_lines": session["candidate_lines"]
                    }
                }
                
            except Exception as e:
                logger.error(f"Error getting conversation history: {e}")
                return {"status": "error", "error": str(e)}
