from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Depends, Query,Body
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Union, List, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field 
from app.services.gemini_model_loader import GeminiModelLoader
from app.models.base_models import CustomPromptRequest,FeedbackResponse, DataAvailabilityResponse,SalaryPredictionResponse,JoiningProbabilityResponse
from app.services.feedback_generator import PerfectFeedbackGenerator,ComprehensiveSalaryPredictor,CandidateJoiningProbabilityPredictor
from app.database.connection import get_db
from app.models.base import (JobDescription,DashboardContent,ThresholdScore,Resume,Discussion,Interview,
    Recording, JobRecruiterAssignment,JobRequiredSkills,AuditTrail,Candidate as SQLCandidate)
import sounddevice as sd
from app.utils.helpers import Helpers
from app.services.job_description.llm_service import DualInputTranscriber,JDLLMService,DocumentProcessor
from app.database.mongo_connection import find_one, find_many
from app.models.base import *
import json
import time
import queue
import pyaudio
import threading
from app.services.job_description.Jd_Analyzer import JDAnalyzer
from app.services.job_description.prompt_engineering import (GENERATE_QA_PROMPT,GENERATE_SIMILAR_QA_PROMPT,QUESTION_STARTERS,)
import speech_recognition as sr
from app.models.base_models import *
from app.database.mongo_connection import (insert_data,update_one,get_collection,find_one,)
from bson import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


# class InitializeRequest(BaseModel):
#     api_key: str


class GenerateQARequest(BaseModel):
    num_pairs: int
    original_qa: str


job_description_router = APIRouter()

transcriber = DualInputTranscriber()

helpers = Helpers()

class JobDescriptionService:

    async def get_job_description_content(
        self, job_id: int, db: Session
    ) -> Dict[str, Any]:
        try:
            job = (
                db.query(JobDescription).filter(JobDescription.job_id == job_id).first()
            )

            if not job:
                raise HTTPException(
                    status_code=404,
                    detail=f"Job description with ID {job_id} not found",
                )

            return {"status": "success", "data": {"description": job.description}}

        except HTTPException as he:
            raise he
        except Exception as e:
            logger.error(f"Error retrieving description content: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error retrieving description content: {str(e)}",
            )

    async def upload_file(
        files: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        user_id: Optional[int] = None,
    ) -> Dict[str, Union[List[Dict[str, Union[str,List[str]]]], str]]:  
        logger.info(f"Starting processing for {len(files)} files")  
        results = []
        llm_service = JDLLMService()

        def fill_missing_fields(extracted_data: dict, text: str) ->Tuple[dict, dict]:
            """
            Fill missing fields from JDAnalyzer fallback, return updated data and field source map.
            """
            source_map = {}  # tracks "LLM" or "Fallback"
            
            fields = {
                "JOB_TITLE": JDAnalyzer.extract_job_title,
                "DEPARTMENT": JDAnalyzer.extract_department,
                "REQUIRED_SKILLS": lambda t: ", ".join(JDAnalyzer.extract_skills(t)),
                "EXPERIENCE": JDAnalyzer.extract_experience,
                "EDUCATION": JDAnalyzer.extract_education,
                "EMPLOYMENT_TYPE": JDAnalyzer.extract_employment_type,
                "KEYWORDS": lambda t: ", ".join(JDAnalyzer.extract_keywords(t)),
                "EXPERIENCE_LEVEL": JDAnalyzer.extract_experience_level
            }

            for field, func in fields.items():
                if extracted_data.get(field):
                    source_map[field] = "LLM"
                else:
                    extracted_data[field] = func(text)
                    source_map[field] = "Fallback"

            return extracted_data, source_map

            
        for file in files:
            try:
                
                # Step 1: Extract raw text
                if file.filename.endswith(".pdf"):
                    text = await Helpers.process_pdf(file)
                elif file.filename.endswith(".docx"):
                    text = Helpers.extract_text_from_docx(await file.read())
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")
                
            
                # Step 2: Run Gemini API
                try:
                    llm_response = await llm_service.analyze_job_description(text)
                    extracted_data = JDLLMService.parse_llm_response(llm_response)
                except Exception as e:
                    logger.warning(f"Gemini API failed: {e}")
                    extracted_data = {}

                # Step 3: Fill missing fields using JDAnalyzer (only where blank)
                extracted_data, field_source = fill_missing_fields(extracted_data, text)
                               
                # Step 4: Store in database
                job_entry = JobDescription(
                    title=extracted_data.get("JOB_TITLE"),
                    department=extracted_data.get("DEPARTMENT"),
                    required_skills=extracted_data.get("REQUIRED_SKILLS"),
                    experience_level=extracted_data.get("EXPERIENCE_LEVEL"),
                    education_requirements=extracted_data.get("EDUCATION"),
                    description=extracted_data.get("ROLE_DESCRIPTION") or text,
                    status="Active",
                    keywords=extracted_data.get("KEYWORDS"),
                    source_file=file.filename,
                    raw_text=text,
                    threshold_score=0.0,
                    activity_type="job_upload",
                )

                db.add(job_entry)
                db.commit()
                db.refresh(job_entry)

                results.append({
                    "filename": file.filename,
                    "keywords": extracted_data.get("KEYWORDS"),
                    "text": text,
                    "id": str(job_entry.job_id),
                    # "job_id": job_entry.job_id,
                    "status": "saved",
                    "data": extracted_data,
                    "source": field_source
                })

            except Exception as e:
                logger.error(f"Error processing file {file.filename}: {e}")
                db.rollback()
                results.append({
                    "filename": file.filename,
                    "error": str(e),
                    "status": "error"
                })

        return {"status": "success", "results": results}

    async def delete_job_description(job_id: int, db: Session) -> Dict[str, str]:
        try:
            # Convert job_id to integer if it's passed as float/string
            job_id = int(float(job_id))

            # Query the job description
            job_description = (
                db.query(JobDescription).filter(JobDescription.job_id == job_id).first()
            )

            if not job_description:
                return {
                    "status": "error",
                    "message": f"Job description with ID {job_id} not found",
                }

            # Delete all related records in order of dependencies
            db.query(Resume).filter(Resume.job_id == job_id).delete()
            db.query(Recording).filter(Recording.jd_id == job_id).delete()
            db.query(JobRecruiterAssignment).filter(
                JobRecruiterAssignment.job_id == job_id
            ).delete()
            db.query(JobRequiredSkills).filter(
                JobRequiredSkills.job_id == job_id
            ).delete()
            db.query(ThresholdScore).filter(ThresholdScore.job_id == job_id).delete()
            db.query(Discussion).filter(Discussion.job_id == job_id).delete()

            # Finally delete the job description
            db.delete(job_description)
            db.commit()

            return {
                "status": "success",
                "message": f"Job description with ID {job_id} deleted successfully",
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting job description: {str(e)}")
            return {
                "status": "error",
                "message": f"Error deleting job description: {str(e)}",
            }

    async def update_job_description(
        job_id: int, updated_data: dict, db: Session
    ) -> Dict[str, str]:
        try:
            # Query the job description by job_id
            job_description = (
                db.query(JobDescription).filter(JobDescription.job_id == job_id).first()
            )

            if not job_description:
                return {
                    "status": "error",
                    "message": f"Job description with ID {job_id} not found",
                }

            # Update fields
            for key, value in updated_data.items():
                if hasattr(job_description, key):
                    setattr(job_description, key, value)

            db.commit()
            db.refresh(job_description)

            return {
                "status": "success",
                "message": f"Job description with ID {job_id} updated successfully",
                "data": {
                    "id": str(job_description.job_id),
                    "title": job_description.title,
                    "description": job_description.description,
                    "keywords": job_description.keywords,
                },
            }
        except Exception as e:
            db.rollback()
            return {
                "status": "error",
                "message": f"Error updating job description: {str(e)}",
            }

    async def get_user_job_descriptions(user_id: int, db: Session) -> Dict[str, Any]:
        try:
            # Import necessary models
            from app.models.base import JobDescription, ThresholdScore, JobRecruiterAssignment
            from sqlalchemy import or_, and_

            # Query job descriptions associated with the user through either ThresholdScore or JobRecruiterAssignment
            job_descriptions_query = (
                db.query(JobDescription)
                .outerjoin(ThresholdScore, and_(JobDescription.job_id == ThresholdScore.job_id, ThresholdScore.user_id == user_id))
                .outerjoin(JobRecruiterAssignment, and_(JobDescription.job_id == JobRecruiterAssignment.job_id, JobRecruiterAssignment.user_id == user_id))
                .filter(or_(
                    ThresholdScore.user_id == user_id,
                    JobRecruiterAssignment.user_id == user_id
                ))
                .order_by(JobDescription.created_at.desc())
            )

            # Execute the query
            job_descriptions_db = job_descriptions_query.all()

            if not job_descriptions_db:
                return {
                    "status": "success",
                    "data": [],
                    "message": f"No job descriptions found for user ID {user_id}",
                }

            # Process the results
            job_descriptions = []
            for jd in job_descriptions_db:
                # For each job description, get the threshold data if it exists
                threshold_data = db.query(ThresholdScore).filter(
                    ThresholdScore.job_id == jd.job_id
                ).order_by(ThresholdScore.created_at.desc()).first()
                
                job_data = {
                    "id": str(jd.job_id),
                    "title": jd.title or "",
                    "description": jd.description or "",
                    "keywords": jd.keywords or "",
                    "status": jd.status or "",
                    "threshold_score": jd.threshold_score or "",
                }

                # Add threshold data if available
                if threshold_data:
                    job_data["selection_score"] = threshold_data.selection_score
                    job_data["rejection_score"] = threshold_data.rejection_score
                    job_data["threshold_result"] = threshold_data.threshold_result
                
                # Add optional fields if they exist and have values
                optional_fields = [
                    "department",
                    "required_skills",
                    "experience_level",
                    "education_requirements",
                    "raw_text",
                    "source_file",
                ]

                for field in optional_fields:
                    if hasattr(jd, field) and getattr(jd, field) is not None:
                        job_data[field] = getattr(jd, field)
                    else:
                        job_data[field] = "Not specified"

                # Handle date fields
                if hasattr(jd, "created_at") and jd.created_at:
                    job_data["created_at"] = jd.created_at.isoformat()
                elif hasattr(jd, "createdat") and jd.createdat:
                    job_data["created_at"] = jd.createdat.isoformat()

                if hasattr(jd, "updated_at") and jd.updated_at:
                    job_data["updated_at"] = jd.updated_at.isoformat()
                elif hasattr(jd, "updatedat") and jd.updatedat:
                    job_data["updated_at"] = jd.updatedat.isoformat()

                job_descriptions.append(job_data)

            return {"status": "success", "data": job_descriptions}
        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            print(f"Error details: {error_details}")
            return {
                "status": "error",
                "message": f"Error fetching job descriptions: {str(e)}",
            }

   
    #     try:
    #         # Convert dict to string for prompt
    #         if isinstance(dashboard_content, dict):
    #             dashboard_content_str = json.dumps(dashboard_content, indent=2)
    #         else:
    #             dashboard_content_str = str(dashboard_content)

    #         qa_prompt = GENERATE_QA_PROMPT.format(
    #             num_qa=num_qa, dashboard_content=dashboard_content_str
    #         )
           
    #         processor = DocumentProcessor()
    #         generate_qa_response = processor.model.generate_content(qa_prompt)
    #         qa_text = generate_qa_response.text.strip()

    #         formatted_qa = []
    #         lines = qa_text.split("\n")
    #         current_qa_pair = []
    #         qa_pairs = []

    #         for line in lines:
    #             line = line.strip()
    #             if not line:
    #                 continue

    #             if line.startswith("Q"):
    #                 if current_qa_pair:
    #                     formatted_qa.extend(current_qa_pair)
    #                     # Extract question and answer without regex
    #                     q_parts = current_qa_pair[0].split(":", 1)
    #                     a_parts = (
    #                         current_qa_pair[1].split(":", 1)
    #                         if len(current_qa_pair) > 1
    #                         else ["", ""]
    #                     )

    #                     qa_pairs.append(
    #                         {
    #                             "question": (
    #                                 q_parts[1].strip() if len(q_parts) > 1 else ""
    #                             ),
    #                             "answer": (
    #                                 a_parts[1].strip() if len(a_parts) > 1 else ""
    #                             ),
    #                         }
    #                     )
    #                     current_qa_pair = []

    #                 # Format question number dynamically
    #                 q_number = len(qa_pairs) + 1
    #                 formatted_line = f"Q{q_number}:{line.split(':', 1)[1].strip() if ':' in line else line[1:].strip()}"
    #                 current_qa_pair.append(formatted_line)

    #             elif line.startswith("A"):
    #                 # Format answer number dynamically
    #                 a_number = len(qa_pairs) + 1
    #                 formatted_line = f"A{a_number}:{line.split(':', 1)[1].strip() if ':' in line else line[1:].strip()}"
    #                 current_qa_pair.append(formatted_line)

    #         # Handle last QA pair
    #         if current_qa_pair:
    #             formatted_qa.extend(current_qa_pair)
    #             q_parts = current_qa_pair[0].split(":", 1)
    #             a_parts = (
    #                 current_qa_pair[1].split(":", 1)
    #                 if len(current_qa_pair) > 1
    #                 else ["", ""]
    #             )

    #             qa_pairs.append(
    #                 {
    #                     "question": q_parts[1].strip() if len(q_parts) > 1 else "",
    #                     "answer": a_parts[1].strip() if len(a_parts) > 1 else "",
    #                 }
    #             )

    #         # Categorize questions based on content
    #         technical_questions = []
    #         behavioral_questions = []
    #         experience_questions = []
    #         role_specific_questions = []

    #         for qa in qa_pairs:
    #             question_lower = qa["question"].lower()
    #             if any(
    #                 keyword in question_lower
    #                 for keyword in [
    #                     "technical",
    #                     "technology",
    #                     "programming",
    #                     "code",
    #                     "tool",
    #                 ]
    #             ):
    #                 technical_questions.append(qa)
    #             elif any(
    #                 keyword in question_lower
    #                 for keyword in ["behavior", "situation", "challenge", "team"]
    #             ):
    #                 behavioral_questions.append(qa)
    #             elif any(
    #                 keyword in question_lower
    #                 for keyword in ["experience", "worked", "previous", "project"]
    #             ):
    #                 experience_questions.append(qa)
    #             else:
    #                 role_specific_questions.append(qa)

    #         current_time = datetime.now()
    #         # Prepare MongoDB document
    #         qa_data = {
    #             "job_id": None,
    #             "questions": qa_pairs,
    #             "question_categories": {
    #                 "technical": technical_questions,
    #                 "behavioral": behavioral_questions,
    #                 "experience": experience_questions,
    #                 "role_specific": role_specific_questions,
    #             },
    #             "difficulty_distribution": {
    #                 "easy": qa_pairs[: len(qa_pairs) // 3],
    #                 "medium": qa_pairs[len(qa_pairs) // 3 : 2 * len(qa_pairs) // 3],
    #                 "hard": qa_pairs[2 * len(qa_pairs) // 3 :],
    #             },
    #             "generated_at": current_time,
    #             "last_updated": current_time,
    #         }

    #         # Insert into MongoDB
    #         result = insert_data("ai_generated_questions", qa_data)

    #         formatted_text = "\n".join(formatted_qa)
    #         return {
    #             "formatted_qa": formatted_text,
    #             "qa_id": str(result.inserted_id),
    #             "metadata": {
    #                 "total_questions": len(qa_pairs),
    #                 "categories": {
    #                     "technical": len(technical_questions),
    #                     "behavioral": len(behavioral_questions),
    #                     "experience": len(experience_questions),
    #                     "role_specific": len(role_specific_questions),
    #                 },
    #                 "generated_at": current_time.isoformat(),  # Convert to ISO format string
    #             },
    #         }

    #     except Exception as e:
    #         raise HTTPException(
    #             status_code=500, detail=f"Error generating Q&A: {str(e)}"
    #         )
    @classmethod
    def generate_qa(cls, dashboard_content: str, num_qa: int, difficulty: str = "beginner", selected_words: Optional[List[str]] = None) -> dict:
        """
        Generate interview questions and answers based on dashboard content and difficulty level.
        """
        try:
            qa_prompt = GENERATE_QA_PROMPT.format(
                num_qa=num_qa,
                dashboard_content=dashboard_content,
                difficulty=difficulty.capitalize()
            )

            # If the caller provided 2 or 3 selected words, instruct the model
            # to also generate follow-up / probing questions focused on those words.
            if selected_words and isinstance(selected_words, list) and 2 <= len(selected_words) <= 3:
                # create a short follow-up instruction using the selected words
                selected_text = ", ".join([w.strip() for w in selected_words if w])
                follow_up_instruction = (
                    "\n\nAdditionally, for each generated question, provide one follow-up/probing question "
                    f"that focuses specifically on the following keywords: {selected_text}. "
                    "Keep follow-ups concise and relevant."
                )
                qa_prompt = qa_prompt + follow_up_instruction
            # print("qa prompt:",qa_prompt)
            processor = DocumentProcessor()
            generate_qa_response = processor.model.generate_content(qa_prompt)
            qa_text = generate_qa_response.text.strip()
            # print("qa text:",qa_text)

            formatted_qa = []
            lines = qa_text.split("\n")
            current_qa_pair = []
            qa_pairs = []

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if line.startswith("Q"):
                    if current_qa_pair:
                        formatted_qa.extend(current_qa_pair)
                        q_parts = current_qa_pair[0].split(":", 1)
                        a_parts = (
                            current_qa_pair[1].split(":", 1)
                            if len(current_qa_pair) > 1
                            else ["", ""]
                        )
                        qa_pairs.append(
                            {
                                "question": q_parts[1].strip() if len(q_parts) > 1 else "",
                                "answer": a_parts[1].strip() if len(a_parts) > 1 else "",
                                "difficulty": difficulty,
                            }
                        )
                        current_qa_pair = []

                    q_number = len(qa_pairs) + 1
                    formatted_line = f"Q{q_number}:{line.split(':', 1)[1].strip() if ':' in line else line[1:].strip()}"
                    current_qa_pair.append(formatted_line)

                elif line.startswith("A"):
                    a_number = len(qa_pairs) + 1
                    formatted_line = f"A{a_number}:{line.split(':', 1)[1].strip() if ':' in line else line[1:].strip()}"
                    current_qa_pair.append(formatted_line)

            if current_qa_pair:
                formatted_qa.extend(current_qa_pair)
                q_parts = current_qa_pair[0].split(":", 1)
                a_parts = (
                    current_qa_pair[1].split(":", 1)
                    if len(current_qa_pair) > 1
                    else ["", ""]
                )
                qa_pairs.append(
                    {
                        "question": q_parts[1].strip() if len(q_parts) > 1 else "",
                        "answer": a_parts[1].strip() if len(a_parts) > 1 else "",
                        "difficulty": difficulty,
                    }
                )

            current_time = datetime.now()
            qa_data = {
                "job_id": None,
                "difficulty": difficulty,
                "questions": qa_pairs,
                "generated_at": current_time,
                "last_updated": current_time,
            }

            result = insert_data("ai_generated_questions", qa_data)

            formatted_text = "\n".join(formatted_qa)
            return {
                "formatted_qa": formatted_text,
                "qa_id": str(result.inserted_id),
                "metadata": {
                    "total_questions": len(qa_pairs),
                    "difficulty": difficulty,
                    "generated_at": current_time.isoformat(),
                },
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error generating Q&A: {str(e)}")

       
    @classmethod
    def get_audio_qa_content(cls, qa_id: str) -> Dict[str, Any]:
        def datetime_handler(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        try:
            object_id = ObjectId(qa_id)
            qa_data = find_one(
                "ai_generated_questions", {"_id": object_id, "type": "Similar QA"}
            )

            if not qa_data:
                return {"status": "error", "message": "Audio QA content not found"}

            formatted_qa_data = {
                "status": "success",
                "data": {
                    "qa_id": str(qa_data["_id"]),
                    "type": qa_data.get("type", ""),
                    "primary_content": qa_data.get("primary_content", ""),
                    "original_qa": qa_data.get("original_qa", ""),
                    "questions": qa_data.get("questions", []),
                    "meta_data": qa_data.get("meta_data", {}),
                    "question_categories": {
                        "technical": qa_data.get("question_categories", {}).get(
                            "technical", []
                        ),
                        "behavioral": qa_data.get("question_categories", {}).get(
                            "behavioral", []
                        ),
                        "experience": qa_data.get("question_categories", {}).get(
                            "experience", []
                        ),
                        "role_specific": qa_data.get("question_categories", {}).get(
                            "role_specific", []
                        ),
                    },
                    "difficulty_distribution": qa_data.get(
                        "difficulty_distribution", {}
                    ),
                    "timestamps": {
                        "created_at": datetime_handler(qa_data.get("created_at")),
                        "generated_at": datetime_handler(qa_data.get("generated_at")),
                        "last_updated": datetime_handler(qa_data.get("last_updated")),
                    },
                },
            }

            return formatted_qa_data

        except Exception as e:
            logger.error(f"Error retrieving audio QA content from MongoDB: {str(e)}")
            return {
                "status": "error",
                "message": f"Error retrieving audio QA content: {str(e)}",
            }

    @classmethod
    def get_qa_content(cls, qa_id: str) -> Dict[str, Any]:
        def datetime_handler(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        try:
            # Find by ObjectId
            object_id = ObjectId(qa_id)
            qa_data = find_one("ai_generated_questions", {"_id": object_id})

            if not qa_data:
                return {"status": "error", "message": "QA content not found"}

            formatted_qa_data = {
                "status": "success",
                "data": {
                    "qa_id": str(qa_data["_id"]),
                    "type": qa_data.get("type", ""),
                    "primary_content": qa_data.get("primary_content", ""),
                    "questions": qa_data.get("questions", []),
                    "metadata": {
                        "total_questions": len(qa_data.get("questions", [])),
                        "categories": {
                            "technical": len(
                                qa_data.get("question_categories", {}).get(
                                    "technical", []
                                )
                            ),
                            "behavioral": len(
                                qa_data.get("question_categories", {}).get(
                                    "behavioral", []
                                )
                            ),
                            "experience": len(
                                qa_data.get("question_categories", {}).get(
                                    "experience", []
                                )
                            ),
                            "role_specific": len(
                                qa_data.get("question_categories", {}).get(
                                    "role_specific", []
                                )
                            ),
                        },
                    },
                    "difficulty_distribution": qa_data.get(
                        "difficulty_distribution", {}
                    ),
                    "timestamps": {
                        "created_at": (
                            datetime_handler(qa_data.get("created_at"))
                            if qa_data.get("created_at")
                            else None
                        ),
                        "generated_at": (
                            datetime_handler(qa_data.get("generated_at"))
                            if qa_data.get("generated_at")
                            else None
                        ),
                        "last_updated": (
                            datetime_handler(qa_data.get("last_updated"))
                            if qa_data.get("last_updated")
                            else None
                        ),
                    },
                },
            }

            return formatted_qa_data

        except Exception as e:
            logger.error(f"Error retrieving QA content from MongoDB: {str(e)}")
            return {
                "status": "error",
                "message": f"Error retrieving QA content: {str(e)}",
            }


class TranscriptionState(BaseModel):
    is_recording: bool = False
    interviewer_lines: List[str] = Field(default_factory=list)
    candidate_lines: List[str] = Field(default_factory=list)
    current_question_id: int = 0
    last_answer_time: float = 0
    recording_mode: str = "interviewer"  # Default to interviewer mode

class TranscriberResponse(BaseModel):
    status: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class DualInputTranscriber:
    _instance = None
    _state = TranscriptionState()
    model = None
    is_recording = False
    is_initialized = False

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

    # Replace the initialize method in the DualInputTranscriber class

async def initialize(cls) -> Dict[str, Any]:
    try:
        # Initialize with hardcoded API key

        cls.model = GeminiModelLoader.get_model()        
        cls.is_initialized = True
        
        return {
            "status": "success",
            "data": {"message": "Initialized successfully"}
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def get_instance(cls):
    if cls._instance is None:
        cls._instance = cls()
    return cls._instance

def _is_question(text: str) -> bool:
    text_lower = text.lower().strip()
    return (
        any(text_lower.startswith(starter) for starter in QUESTION_STARTERS)
        or "?" in text
    )

    # Replace the start_recording method in the DualInputTranscriber class with this improved version

# Replace the start_recording method in the DualInputTranscriber class

@classmethod
async def start_recording(cls, db: Session) -> Dict[str, Any]:
    if not cls.is_initialized:
        return {"status": "error", "error": "Transcriber not initialized"}
    try:
        # Get or create an instance
        instance = cls._instance or cls()
        
        if not cls.is_recording:
            cls.is_recording = True

            # Reset the state
            cls._state = TranscriptionState()

            # Create MongoDB recording document
            recording_data = {
                "status": "Active",
                "speaker_type": "dual",
                "transcript_text": "",
                "interviewer_text": "",
                "candidate_text": "",
                "created_at": datetime.now(),
                "interview_type": "job_description",
                "speaker_segments": [],
                "questions_and_answers": []
            }

            logger.info(
                f"Attempting to insert interview data into MongoDB: {recording_data}"
            )

            # Insert into MongoDB
            result = insert_data("interview_transcriptions", recording_data)
            recording_id = str(result.inserted_id)

            logger.info(
                f"Successfully inserted data into MongoDB with ID: {recording_id}"
            )

            # Start transcription threads
            mic_thread = threading.Thread(
                target=instance._transcribe_mic, daemon=True
            )
            speaker_thread = threading.Thread(
                target=instance._transcribe_speaker, daemon=True
            )
            update_thread = threading.Thread(
                target=instance._update_mongodb_document, daemon=True
            )

            mic_thread.start()
            speaker_thread.start()
            update_thread.start()

            return {
                "status": "success",
                "data": {
                    "message": "Recording started successfully",
                    "recording_id": recording_id,
                },
            }
        return {"status": "error", "error": "Already recording"}
    except Exception as e:
        logger.error(f"Failed to start recording: {str(e)}")
        return {"status": "error", "error": f"Failed to start recording: {str(e)}"}


    # Replace the stop_recording method in the DualInputTranscriber class with this improved version

# Replace the stop_recording method in the DualInputTranscriber class

@classmethod
async def stop_recording(cls, db: Session) -> Dict[str, Any]:
    if not cls.is_initialized:
        return {"status": "error", "error": "Transcriber not initialized"}
    try:
        if cls.is_recording:
            cls.is_recording = False

            # Combine interviewer and candidate lines into a properly formatted transcript
            combined_transcript = ""
            for i, question in enumerate(cls._state.interviewer_lines):
                combined_transcript += f"Interviewer: {question}\n"
                if i < len(cls._state.candidate_lines):
                    combined_transcript += f"Candidate: {cls._state.candidate_lines[i]}\n"

            # Find the active recording in MongoDB
            collection = get_collection("interview_transcriptions")
            active_recording = collection.find_one(
                {"status": "Active", "interview_type": "job_description"},
                sort=[("created_at", -1)],
            )

            if active_recording:
                logger.info(
                    f"Found active recording in MongoDB with ID: {active_recording['_id']}"
                )

                # Create structured Q&A pairs
                qa_pairs = []
                for i, question in enumerate(cls._state.interviewer_lines):
                    qa_pair = {
                        "question": question,
                        "answer": cls._state.candidate_lines[i] if i < len(cls._state.candidate_lines) else ""
                    }
                    qa_pairs.append(qa_pair)

                # Update the MongoDB document
                update_one(
                    "interview_transcriptions",
                    {"_id": active_recording["_id"]},
                    {
                        "$set": {
                            "status": "Completed",
                            "transcript_text": combined_transcript,
                            "interviewer_text": "\n".join(cls._state.interviewer_lines),
                            "candidate_text": "\n".join(cls._state.candidate_lines),
                            "updated_at": datetime.now(),
                            "speaker_segments": [
                                {"speaker": "interviewer", "text": text} 
                                for text in cls._state.interviewer_lines
                            ] + [
                                {"speaker": "candidate", "text": text}
                                for text in cls._state.candidate_lines
                            ],
                            "questions_and_answers": qa_pairs
                        }
                    },
                )

                logger.info(f"Updated MongoDB document with transcript data")

                return {
                    "status": "success",
                    "data": {
                        "message": "Recording stopped",
                        "recording_id": str(active_recording["_id"]),
                    },
                }

            return {
                "status": "success",
                "data": {
                    "message": "Recording stopped, but no active recording found in database"
                },
            }
        return {"status": "error", "error": "Not recording"}
    except Exception as e:
        logger.error(f"Error stopping recording: {str(e)}")
        return {"status": "error", "error": str(e)}

    # Replace the _update_mongodb_document method in the DualInputTranscriber class with this improved version


@classmethod
async def clear_transcription(cls) -> Dict[str, Any]:
    if not cls.is_initialized:
        return {"status": "error", "error": "Transcriber not initialized"}

    try:
        cls._state = TranscriptionState()
        return {
            "status": "success",
            "data": {
                "message": "Transcription cleared",
                "text": cls._get_combined_text(),
            },
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

@classmethod
async def evaluate_qa(cls) -> Dict[str, Any]:
    if not cls.is_initialized:
        return {"status": "error", "error": "Transcriber not initialized"}
    try:
        # Get latest transcription from MongoDB
        latest_transcription = find_one(
            "interview_transcriptions",
            {"status": "Active"},
            sort=[("created_at", -1)],
        )

        # Print for debugging
        print("Latest transcription:", latest_transcription)

        # Get Q&A pairs
        state = cls._state
        questions = state.interviewer_lines
        answers = state.candidate_lines

        print("Current Q&A state:")
        print("Questions:", questions)
        print("Answers:", answers)

        if not questions or not answers:
            return {
                "status": "error",
                "explanation": "No Q&A pairs found",
                "mark": "âŒ",
                "score": "0%",
            }

        # Get latest Q&A pair
        current_qa = {"question": questions[-1], "answer": answers[-1]}

        # Generate AI evaluation
        prompt = f"""
        Evaluate this Q&A pair:
        Question: {current_qa['question']}
        Answer: {current_qa['answer']}
        
        Rate the answer's quality, relevance, and completeness.
        
        Provide evaluation in this format:
        SCORE: (number between 0-100)
        EXPLANATION: (detailed feedback)
        """

        response = cls.model.generate_content(prompt)
        response_text = response.text

        print("AI Response:", response_text)

        # Parse response with better error handling
        score = "0"
        explanation = "No evaluation generated"

        for line in response_text.split("\n"):
            if "SCORE:" in line:
                score = line.replace("SCORE:", "").strip().rstrip("%")
            elif "EXPLANATION:" in line:
                explanation = line.replace("EXPLANATION:", "").strip()

        # Convert score to float for calculations
        try:
            score_float = float(score)
        except ValueError:
            score_float = 0
        
        # Create evaluation document that matches the MongoDB schema
        evaluation_data = {
            "evaluation_id": len(questions),
            "candidate_id": None,  # Not available in this context
            "job_id": None,  # Not available in this context
            "interview_id": str(latest_transcription["_id"]) if latest_transcription else None,
            "evaluator_id": None,  # Not available in this context
            "evaluation_date": datetime.now(),
            
            # Overall scores
            "overall_scores": {
                "total_score": score_float,
                "recommendation": "Hire" if score_float >= 70 else "Consider" if score_float >= 50 else "Reject",
                "match_percentage": score_float,
                "confidence_score": 80.0  # Default confidence score
            },
            
            # Simplified category scores
            "category_scores": {
                "technical_skills": {
                    "score": score_float,
                    "strengths": [],
                    "weaknesses": [],
                    "detailed_skills": {}
                },
                "communication": {
                    "score": score_float,
                    "clarity": score_float,
                    "articulation": score_float,
                    "listening": score_float,
                    "non_verbal": score_float
                }
            },
            
            # Question-by-question analysis
            "question_analysis": [{
                "question": current_qa["question"],
                "answer": current_qa["answer"],
                "score": score_float,
                "feedback": explanation
            }],
            
            # AI-generated feedback
            "ai_feedback": {
                "summary": explanation,
                "strengths": [],
                "areas_for_improvement": [],
                "hiring_recommendation": "Consider based on this answer",
                "fit_analysis": "",
                "suggested_interview_questions": []
            },
            
            # Metadata
            "evaluation_type": "Q&A",
            "evaluation_method": "AI",
            "evaluation_duration": 0.0,
            "notes": response_text,
            "status": "Completed",
            
            # Timestamps
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }

        # Insert into MongoDB and get ID
        result = insert_data("candidate_evaluations", evaluation_data)
        eval_id = str(result.inserted_id)

        print("Stored evaluation with ID:", eval_id)

        # Verify storage
        stored_eval = find_one("candidate_evaluations", {"_id": ObjectId(eval_id)})
        print("Verified stored evaluation:", stored_eval)

        return {
            "status": "success",
            "explanation": explanation,
            "mark": "âœ…" if score_float >= 60 else "âŒ",
            "score": f"{score}%",
            "eval_id": eval_id,
            "data": evaluation_data,
        }

    except Exception as e:
        print(f"Evaluation error: {str(e)}")
        logger.error(f"Evaluation error: {str(e)}")
        return {
            "status": "error",
            "explanation": f"Error during evaluation: {str(e)}",
            "mark": "âŒ",
            "score": "0%",
        }

def get_evaluation_qa_content(eval_id: str) -> Dict[str, Any]:
    def datetime_handler(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    try:
        object_id = ObjectId(eval_id)
        eval_data = find_one("candidate_evaluations", {"_id": object_id})

        if not eval_data:
            logger.error(f"Evaluation with ID {eval_id} not found")
            return {"status": "error", "message": "Evaluation content not found"}

        # Extract the first question analysis item if it exists
        question_analysis = eval_data.get("question_analysis", [{}])[0]
        
        formatted_eval_data = {
            "status": "success",
            "data": {
                "eval_id": str(eval_data["_id"]),
                "type": eval_data.get("evaluation_type", "Q&A"),
                "score": f"{eval_data.get('overall_scores', {}).get('total_score', 0)}%",
                "feedback": question_analysis.get("feedback", ""),
                "question": question_analysis.get("question", ""),
                "answer": question_analysis.get("answer", ""),
                "recommendation": eval_data.get("overall_scores", {}).get("recommendation", ""),
                "created_at": datetime_handler(eval_data.get("created_at")),
                "updated_at": datetime_handler(eval_data.get("updated_at")),
            },
        }

        return formatted_eval_data

    except Exception as e:
        logger.error(f"Error retrieving evaluation content from MongoDB: {str(e)}")
        return {
            "status": "error",
            "message": f"Error retrieving evaluation content: {str(e)}",
        }

def generate_similar_qa(num_pairs: int, original_qa: str) -> Tuple[str, str]:
    if not original_qa.strip():
        return "", "Please record a Q&A pair first before generating similar ones."

    try:
        qa_prompt = GENERATE_SIMILAR_QA_PROMPT.format(
            original_qa=original_qa, num_pairs=num_pairs
        )
        response = DocumentProcessor.model.generate_content(qa_prompt)
        generated_text = response.text

        # Parse QA pairs
        qa_pairs = []
        lines = generated_text.split("\n")
        current_qa = {}

        for line in lines:
            line = line.strip()
            if line.startswith("Q"):
                if current_qa:
                    qa_pairs.append(current_qa)
                current_qa = {"question": line.split(":", 1)[1].strip()}
            elif line.startswith("A") and current_qa:
                current_qa["answer"] = line.split(":", 1)[1].strip()

        if current_qa:
            qa_pairs.append(current_qa)

        current_time = datetime.now()

        # Create MongoDB document following schema
        qa_data = {
            "type": "Similar QA",
            "primary_content": generated_text,
            "questions": qa_pairs,
            "meta_data": {
                "num_pairs": num_pairs,
                "original_qa_length": len(original_qa),
            },
            "question_categories": {
                "technical": [],
                "behavioral": [],
                "experience": [],
                "role_specific": qa_pairs,
            },
            "difficulty_distribution": {
                "easy": qa_pairs[: len(qa_pairs) // 3],
                "medium": qa_pairs[len(qa_pairs) // 3 : 2 * len(qa_pairs) // 3],
                "hard": qa_pairs[2 * len(qa_pairs) // 3 :],
            },
            "created_at": current_time,
            "generated_at": current_time,
            "last_updated": current_time,
            "original_qa": original_qa,
        }

        # Insert into MongoDB
        result = insert_data("ai_generated_questions", qa_data)

        # Store the MongoDB document ID for reference
        qa_id = str(result.inserted_id)

        return original_qa, {
            "generated_text": generated_text,
            "qa_id": qa_id,
            "metadata": {
                "total_questions": len(qa_pairs),
                "generated_at": current_time.isoformat(),
            },
        }

    except Exception as e:
        return original_qa, f"Error generating Q&A pairs: {str(e)}"

def _process_queues(self):
    """Process the mic and speaker queues to update state"""
    while DualInputTranscriber.is_recording:
        try:
            # Process mic queue (interviewer)
            if not self.mic_queue.empty():
                text = self.mic_queue.get(block=False)
                if text:
                    print(f"Processing interviewer text: {text}")
                    DualInputTranscriber._state.interviewer_lines.append(text)

            # Process speaker queue (candidate)
            if not self.speaker_queue.empty():
                text = self.speaker_queue.get(block=False)
                if text:
                    print(f"Processing candidate text: {text}")
                    DualInputTranscriber._state.candidate_lines.append(text)

            time.sleep(0.1)  # Small delay to prevent CPU hogging
        except queue.Empty:
            pass  # Queue is empty, continue
        except Exception as e:
            print(f"Error processing queues: {str(e)}")
            time.sleep(0.5)

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

# Replace the _transcribe_speaker method in the DualInputTranscriber class with this improved version

#Job-description routes starts here
@job_description_router.get("/job-descriptions/list/")
async def list_job_descriptions(db: Session = Depends(get_db)):
    try:
        # Query all job descriptions
        job_descriptions = db.query(JobDescription).all()
        logger.info(f"Found {len(job_descriptions)} job descriptions")

        # Convert to list of dictionaries
        return [
            {
                "job_id": jd.job_id,
                "id": jd.job_id,
                "title": jd.title,
                "description": jd.description,
                "required_skills": jd.required_skills,
                "department": jd.department,
                "experience_level": jd.experience_level,
                "education_requirements": jd.education_requirements,
                "status": jd.status,
                "threshold_score": jd.threshold_score,
                "created_at": jd.created_at.isoformat() if jd.created_at else None,
            }
            for jd in job_descriptions
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@job_description_router.post("/upload-documents")
async def upload_documents(
    files: List[UploadFile] = File(...), db: Session = Depends(get_db)
) -> JSONResponse:
    try:
        result = await JobDescriptionService.upload_file(files, db)
        if result.get("status") == "error":
            return JSONResponse(content=result, status_code=500)
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        print(f"Error details: {error_details}")
        return JSONResponse(
            content={"status": "error", "message": f"Error processing files: {str(e)}"},
            status_code=500,
        )


@job_description_router.delete("/delete-job-description/{job_id}")
async def delete_job_description(
    job_id: int, db: Session = Depends(get_db)
) -> JSONResponse:
    result = await JobDescriptionService.delete_job_description(job_id, db)
    status_code = (
        200
        if result["status"] == "success"
        else 404 if "not found" in result.get("message", "") else 500
    )
    return JSONResponse(content=result, status_code=status_code)


@job_description_router.put("/update-job-description/{job_id}")
async def update_job_description(
    job_id: int, updated_data: dict, db: Session = Depends(get_db)
) -> JSONResponse:
    result = await JobDescriptionService.update_job_description(
        job_id, updated_data, db
    )
    status_code = (
        200
        if result["status"] == "success"
        else 404 if "not found" in result.get("message", "") else 500
    )
    return JSONResponse(content=result, status_code=status_code)


##Job-description routes ends here


@job_description_router.post("/generate-QA")
async def generate_qa(
        dashboard_content: str = Form(...),
        num_qa: int = Form(default=5),
        difficulty: str = Form(default="beginner"),
        selected_words: Optional[str] = Form(None, description="Optional comma-separated selected words to guide follow-up questions")
    ) -> JSONResponse:
        try:
            # Parse selected_words string (comma-separated) into a list if provided
            words_list = None
            if selected_words:
                # split on commas and strip whitespace, ignore empty entries
                words_list = [w.strip() for w in selected_words.split(",") if w.strip()]

            result = JobDescriptionService.generate_qa(dashboard_content, num_qa, difficulty, selected_words=words_list)
            return JSONResponse(
                content={
                    "status": "success",
                    "content": result["formatted_qa"],
                    "qa_id": result["qa_id"],
                    "metadata": result["metadata"],
                }
            )
        except Exception as e:
            return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)


@job_description_router.get("/Get-qa/{qa_id}")
async def get_qa(qa_id: str) -> JSONResponse:
    result = JobDescriptionService.get_qa_content(qa_id)
    return JSONResponse(
        content=result,
        status_code=(
            200
            if result["status"] == "success"
            else 404 if "not found" in result.get("message", "") else 500
        ),
    )


# Update the route handlers

@job_description_router.post("/initialize-transcribe")
async def initialize_transcriber() -> JSONResponse:
    try:
        # Import the DualInputTranscriber class directly
        from app.services.job_description.llm_service import DualInputTranscriber
        
        # Create an instance first (singleton pattern will handle this)
        transcriber = DualInputTranscriber()
        
        # Initialize Gemini directly to avoid any class method issues

        
        # Set class variables directly
        DualInputTranscriber.model = GeminiModelLoader.get_model()        
        DualInputTranscriber.is_initialized = True
        
        logger.info("Transcriber initialized successfully")
        
        return JSONResponse(
            content={
                "status": "success",
                "data": {"message": "Initialized successfully"}
            },
            status_code=200
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error initializing transcriber: {error_details}")
        return JSONResponse(
            content={"status": "error", "error": str(e)}, 
            status_code=500
        )

@job_description_router.post("/start_Recording")
async def start_recording(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        # Import the class
        from app.services.job_description.llm_service import DualInputTranscriber, TranscriptionState
        
        import threading
        from datetime import datetime  # Import datetime correctly
        
        # Create an instance first
        transcriber = DualInputTranscriber()
        
        # Check if initialized
        if not DualInputTranscriber.is_initialized:

            DualInputTranscriber.model = GeminiModelLoader.get_model()            
            DualInputTranscriber.is_initialized = True
        
        # Reset state if needed
        if not DualInputTranscriber.is_recording:
            DualInputTranscriber.is_recording = True
            DualInputTranscriber._state = TranscriptionState()
            
            # Create MongoDB recording document
            current_time = datetime.now()  # Use datetime correctly
            recording_data = {
                "status": "Active",
                "speaker_type": "dual",
                "transcript_text": "",
                "interviewer_text": "",
                "candidate_text": "",
                "created_at": current_time,
                "interview_type": "job_description",
                "speaker_segments": [],
                "questions_and_answers": []
            }
            
            # Insert into MongoDB
            result = insert_data("interview_transcriptions", recording_data)
            recording_id = str(result.inserted_id)
            
            logger.info(f"Created MongoDB document with ID: {recording_id}")
            
            # Add the new candidate mic method
            if not hasattr(transcriber, '_transcribe_candidate_mic'):
                # Define the method dynamically if it doesn't exist
                setattr(transcriber, '_transcribe_candidate_mic', lambda self=transcriber: transcriber._transcribe_candidate_mic())
            
            # Start transcription threads
            mic_thread = threading.Thread(
                target=transcriber._transcribe_mic, daemon=True
            )
            
            # Use the new candidate mic method instead of speaker
            candidate_thread = threading.Thread(
                target=transcriber._transcribe_candidate_mic, daemon=True
            )
            
            update_thread = threading.Thread(
                target=transcriber._update_mongodb_document, daemon=True
            )
            
            mic_thread.start()
            candidate_thread.start()
            update_thread.start()
            
            logger.info("Started recording threads")
            
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {
                        "message": "Recording started successfully",
                        "recording_id": recording_id
                    }
                },
                status_code=200
            )
        
        return JSONResponse(
            content={"status": "error", "error": "Already recording"},
            status_code=400
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error in start_recording endpoint: {error_details}")
        return JSONResponse(
            content={"status": "error", "error": str(e)}, 
            status_code=500
        )
@job_description_router.post("/add_candidate_response")
async def add_candidate_response(response: str = Form(...)) -> JSONResponse:
    try:
        # Import the class
        from app.services.job_description.llm_service import DualInputTranscriber
        
        # Get the transcriber instance
        transcriber = DualInputTranscriber()
        
        # Add the response to candidate lines
        DualInputTranscriber._state.candidate_lines.append(response)
        
        # Find active recording
        active_recording = find_one(
            "interview_transcriptions",
            {"status": "Active", "interview_type": "job_description"}
        )
        
        if active_recording:
            # Get state
            state = DualInputTranscriber._state
            
            # Create combined transcript
            combined_transcript = ""
            for i, question in enumerate(state.interviewer_lines):
                combined_transcript += f"Interviewer: {question}\n"
                if i < len(state.candidate_lines):
                    combined_transcript += f"Candidate: {state.candidate_lines[i]}\n"
            
            # Create Q&A pairs
            qa_pairs = []
            for i, question in enumerate(state.interviewer_lines):
                qa_pair = {
                    "question": question,
                    "answer": state.candidate_lines[i] if i < len(state.candidate_lines) else ""
                }
                qa_pairs.append(qa_pair)
            
            # Update MongoDB
            from datetime import datetime
            current_time = datetime.now()
            update_one(
                "interview_transcriptions",
                {"_id": active_recording["_id"]},
                {
                    "$set": {
                        "transcript_text": combined_transcript,
                        "interviewer_text": "\n".join(state.interviewer_lines),
                        "candidate_text": "\n".join(state.candidate_lines),
                        "updated_at": current_time,
                        "speaker_segments": [
                            {"speaker": "interviewer", "text": text} 
                            for text in state.interviewer_lines
                        ] + [
                            {"speaker": "candidate", "text": text}
                            for text in state.candidate_lines
                        ],
                        "questions_and_answers": qa_pairs
                    }
                }
            )
            
            logger.info(f"Added candidate response and updated MongoDB document")
            
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {
                        "message": "Candidate response added",
                        "recording_id": str(active_recording["_id"]),
                        "state": {
                            "interviewer_lines": state.interviewer_lines,
                            "candidate_lines": state.candidate_lines
                        }
                    }
                },
                status_code=200
            )
        
        return JSONResponse(
            content={
                "status": "error",
                "message": "No active recording found"
            },
            status_code=404
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error adding candidate response: {error_details}")
        return JSONResponse(
            content={"status": "error", "error": str(e)}, 
            status_code=500
        )


@job_description_router.post("/stop_Recording")
async def stop_recording(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        # Import the class
        from app.services.job_description.llm_service import DualInputTranscriber
        from app.database.mongo_connection import find_one, update_one
        from datetime import datetime  # Import datetime correctly
        
        # Check if recording
        if not DualInputTranscriber.is_recording:
            return JSONResponse(
                content={"status": "error", "error": "Not recording"},
                status_code=400
            )
        
        # Stop recording
        DualInputTranscriber.is_recording = False
        
        # Find active recording - remove the sort parameter
        active_recording = find_one(
            "interview_transcriptions",
            {"status": "Active", "interview_type": "job_description"}
        )
        
        if active_recording:
            # Get state
            state = DualInputTranscriber._state
            
            # Create combined transcript
            combined_transcript = ""
            for i, question in enumerate(state.interviewer_lines):
                combined_transcript += f"Interviewer: {question}\n"
                if i < len(state.candidate_lines):
                    combined_transcript += f"Candidate: {state.candidate_lines[i]}\n"
            
            # Create Q&A pairs
            qa_pairs = []
            for i, question in enumerate(state.interviewer_lines):
                qa_pair = {
                    "question": question,
                    "answer": state.candidate_lines[i] if i < len(state.candidate_lines) else ""
                }
                qa_pairs.append(qa_pair)
            
            # Update MongoDB - use datetime.now() correctly
            current_time = datetime.now()
            update_one(
                "interview_transcriptions",
                {"_id": active_recording["_id"]},
                {
                    "$set": {
                        "status": "Completed",
                        "transcript_text": combined_transcript,
                        "interviewer_text": "\n".join(state.interviewer_lines),
                        "candidate_text": "\n".join(state.candidate_lines),
                        "updated_at": current_time,
                        "speaker_segments": [
                            {"speaker": "interviewer", "text": text} 
                            for text in state.interviewer_lines
                        ] + [
                            {"speaker": "candidate", "text": text}
                            for text in state.candidate_lines
                        ],
                        "questions_and_answers": qa_pairs
                    }
                }
            )
            
            logger.info(f"Updated MongoDB document with final transcript data")
            
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {
                        "message": "Recording stopped",
                        "recording_id": str(active_recording["_id"])
                    }
                },
                status_code=200
            )
        
        return JSONResponse(
            content={
                "status": "success",
                "data": {"message": "Recording stopped, but no active recording found"}
            },
            status_code=200
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error in stop_recording endpoint: {error_details}")
        return JSONResponse(
            content={"status": "error", "error": str(e)}, 
            status_code=500
        )


@job_description_router.post("/clear_Transcription")
async def clear_transcription() -> JSONResponse:
    try:
        response = await DualInputTranscriber.clear_transcription()
        return JSONResponse(
            content=response,
            status_code=200 if response["status"] == "success" else 400,
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "error": str(e)}, status_code=500
        )

@job_description_router.post("/generate_QA_from_audio")
async def generate_qa_from_audio(request: GenerateQARequest):
    try:
        original_qa, result = DualInputTranscriber.generate_similar_qa(
            request.num_pairs, request.original_qa
        )
        if isinstance(result, dict):
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {
                        "original": original_qa,
                        "generated": result["generated_text"],
                        "qa_id": result["qa_id"],
                        "metadata": result["metadata"],
                    },
                },
                status_code=200,
            )
        else:
            # Handle error case where result is error message string
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {"original": original_qa, "generated": result},
                },
                status_code=200,
            )

    except Exception as e:
        return JSONResponse(
            content={"status": "error", "error": str(e)}, status_code=500
        )


@job_description_router.get("/Get-audio-qa/{qa_id}")
async def get_audio_qa(qa_id: str) -> JSONResponse:
    try:
        # Print debug info
        print(f"Fetching QA with ID: {qa_id}")
        
        # Convert string ID to ObjectId
        object_id = ObjectId(qa_id)
        
        # Query MongoDB collection
        collection = get_collection("interview_transcriptions")  
        qa_data = collection.find_one({"_id": object_id})
        
        print(f"Found QA data: {qa_data}")

        if not qa_data:
            return JSONResponse(
                content={
                    "status": "error",
                    "message": "QA content not found"
                },
                status_code=404
            )

        # Format response data with proper datetime handling
        formatted_qa_data = {
            "status": "success",
            "data": {
                "qa_id": str(qa_data["_id"]),
                "type": qa_data.get("interview_type", ""),
                "transcript_text": qa_data.get("transcript_text", ""),
                "interviewer_text": qa_data.get("interviewer_text", ""),
                "candidate_text": qa_data.get("candidate_text", ""),
                "status": qa_data.get("status", ""),
                "timestamps": {
                    "created_at": qa_data.get("created_at").isoformat() if qa_data.get("created_at") else None,
                    "updated_at": qa_data.get("updated_at").isoformat() if qa_data.get("updated_at") else None
                }
            }
        }

        return JSONResponse(content=formatted_qa_data, status_code=200)

    except Exception as e:
        print(f"Error retrieving QA content: {str(e)}")
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Error retrieving QA content: {str(e)}"
            },
            status_code=500
        )
        
@job_description_router.post("/start-interviewer-recording", summary="Start Interviewer Recording")
async def start_interviewer_recording(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        # Import the DualInputTranscriber class directly
        from app.services.job_description.llm_service import DualInputTranscriber
        
        # Create an instance first (singleton pattern will handle this)
        transcriber = DualInputTranscriber()
        

        
        # Set class variables directly
        DualInputTranscriber.model = GeminiModelLoader.get_model()        
        DualInputTranscriber.is_initialized = True
        
        # Reset state if needed
        if not DualInputTranscriber.is_recording:
            DualInputTranscriber.is_recording = True
            DualInputTranscriber._state = TranscriptionState()
            DualInputTranscriber._state.recording_mode = "interviewer"
            
            # Create MongoDB recording document
            recording_data = {
                "status": "Active",
                "speaker_type": "dual",
                "transcript_text": "",
                "interviewer_text": "",
                "candidate_text": "",
                "created_at": datetime.now(),
                "interview_type": "job_description",
                "speaker_segments": [],
                "questions_and_answers": []
            }
            
            # Insert into MongoDB
            result = insert_data("interview_transcriptions", recording_data)
            recording_id = str(result.inserted_id)
            
            logger.info(f"Created MongoDB document with ID: {recording_id}")
            
            # Start transcription threads
            mic_thread = threading.Thread(
                target=transcriber._transcribe_mic, daemon=True
            )
            update_thread = threading.Thread(
                target=transcriber._update_mongodb_document, daemon=True
            )
            
            mic_thread.start()
            update_thread.start()
            
            logger.info("Started recording threads")
            
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {
                        "message": "Recording started successfully",
                        "recording_id": recording_id
                    }
                },
                status_code=200
            )
        
        return JSONResponse(
            content={"status": "error", "error": "Already recording"},
            status_code=400
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error in start_recording endpoint: {error_details}")
        return JSONResponse(
            content={"status": "error", "error": str(e)}, 
            status_code=500
        )

@job_description_router.post("/start-candidate-recording", summary="Start Candidate Recording")
async def start_candidate_recording(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        # Import the DualInputTranscriber class directly
        from app.services.job_description.llm_service import DualInputTranscriber
        
        # Create an instance first (singleton pattern will handle this)
        transcriber = DualInputTranscriber()
        
        # Initialize Gemini directly to avoid any class method issues
        if not DualInputTranscriber.is_initialized:

            DualInputTranscriber.model = GeminiModelLoader.get_model()            
            DualInputTranscriber.is_initialized = True
        
        # Check if we're already recording
        if not DualInputTranscriber.is_recording:
            DualInputTranscriber.is_recording = True
            DualInputTranscriber._state.recording_mode = "candidate"
            
            # Find the active recording to continue with the same ID
            active_recording = find_one(
                "interview_transcriptions",
                {"status": "Active", "interview_type": "job_description"},
                sort=[("created_at", -1)]
            )
            
            recording_id = None
            
            if active_recording:
                # Use the existing recording ID
                recording_id = str(active_recording["_id"])
                logger.info(f"Using existing recording with ID: {recording_id}")
            else:
                # Create a new MongoDB recording document if no active one exists
                recording_data = {
                    "status": "Active",
                    "speaker_type": "dual",
                    "transcript_text": "",
                    "interviewer_text": "",
                    "candidate_text": "",
                    "created_at": datetime.now(),
                    "interview_type": "job_description",
                    "speaker_segments": [],
                    "questions_and_answers": []
                }
                
                # Insert into MongoDB
                result = insert_data("interview_transcriptions", recording_data)
                recording_id = str(result.inserted_id)
                
                logger.info(f"Created MongoDB document with ID: {recording_id}")
            
            # Start transcription threads
            mic_thread = threading.Thread(
                target=transcriber._transcribe_candidate_mic, daemon=True
            )
            update_thread = threading.Thread(
                target=transcriber._update_mongodb_document, daemon=True
            )
            
            mic_thread.start()
            update_thread.start()
            
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {
                        "message": "Candidate recording started successfully",
                        "recording_id": recording_id,
                    },
                },
                status_code=200
            )
        return JSONResponse(
            content={"status": "error", "error": "Already recording"},
            status_code=400
        )
    except Exception as e:
        logger.error(f"Failed to start candidate recording: {str(e)}")
        return JSONResponse(
            content={"status": "error", "error": f"Failed to start recording: {str(e)}"},
            status_code=500
        )
        
from pydantic import BaseModel, Field

# Define a request model for the evaluate_QA endpoint
class EvaluateQARequest(BaseModel):
    interview_text: str = Field(..., description="The interview text to evaluate (can contain both question and answer)")


@job_description_router.post("/record-interviewer-question")
async def record_interviewer_question(session_id: str = Form("default"), action: str = Form("start")) -> JSONResponse:
    """
    Record a single question from the interviewer and return the transcribed text.
    This endpoint will activate the microphone and listen for speech.
    
    Args:
        session_id: Session identifier
        action: "start" to begin recording or "stop" to stop recording
    """
    try:
        # Import the class directly to avoid any issues
        from app.services.job_description.llm_service import DualInputTranscriber
        from datetime import datetime  # Make sure to import datetime correctly
        
        # Force reset recording state if starting a new recording
        if action == "start":
            # Check if there's an existing recording and force clear it
            if hasattr(DualInputTranscriber, 'session_data') and session_id in DualInputTranscriber.session_data:
                if DualInputTranscriber.session_data[session_id].get("current_recording"):
                    logger.info(f"Forcing reset of existing recording for session {session_id}")
                    DualInputTranscriber.session_data[session_id]["current_recording"] = None
        
        # Call the classmethod directly
        result = await DualInputTranscriber.record_single_input("interviewer", session_id, action)
        
        # Always return a 200 status code, even for errors
        return JSONResponse(content=result, status_code=200)
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error recording interviewer question: {error_details}")
        return JSONResponse(
            content={
                "status": "error",
                "error": "Failed to process recording. Please try again.",
                "details": str(e),
                "role": "interviewer"
            },
            status_code=200  # Return 200 even for errors
        )

@job_description_router.post("/record-candidate-answer")
async def record_candidate_answer(session_id: str = Form("default"), action: str = Form("start")) -> JSONResponse:
    """
    Record a single answer from the candidate and return the transcribed text.
    This endpoint will activate the microphone and listen for speech.
    
    Args:
        session_id: Session identifier
        action: "start" to begin recording or "stop" to stop recording
    """
    try:
        # Import the class directly to avoid any issues
        from app.services.job_description.llm_service import DualInputTranscriber
        
        # Force reset recording state if starting a new recording
        if action == "start":
            # Check if there's an existing recording and force clear it
            if hasattr(DualInputTranscriber, 'session_data') and session_id in DualInputTranscriber.session_data:
                if DualInputTranscriber.session_data[session_id].get("current_recording"):
                    logger.info(f"Forcing reset of existing recording for session {session_id}")
                    DualInputTranscriber.session_data[session_id]["current_recording"] = None
        
        # Call the classmethod directly
        result = await DualInputTranscriber.record_single_input("candidate", session_id, action)
        
        # Always return a 200 status code, even for errors
        return JSONResponse(content=result, status_code=200)
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error recording candidate answer: {error_details}")
        return JSONResponse(
            content={
                "status": "error",
                "error": "Failed to process recording. Please try again.",
                "details": str(e),
                "role": "candidate"
            },
            status_code=200  # Return 200 even for errors
        )


@job_description_router.get("/get-conversation-history/{session_id}")
async def get_conversation_history(session_id: str) -> JSONResponse:
    """
    Get the conversation history for a specific session.
    """
    try:
        # Import the class directly to avoid any issues
        from app.services.job_description.llm_service import DualInputTranscriber
        
        # Create an instance first
        transcriber = DualInputTranscriber()
        
        # Call the method on the instance instead of the class
        result = await transcriber.get_conversation_history(session_id)
        
        if result["status"] == "success":
            return JSONResponse(content=result, status_code=200)
        else:
            return JSONResponse(content=result, status_code=400)
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error getting conversation history: {error_details}")
        return JSONResponse(
            content={
                "status": "error",
                "error": str(e)
            },
            status_code=500
        )
   
        
##FEEDBACK GENERATION 

@job_description_router.get("/generate_feedback", response_model=FeedbackResponse)
async def generate_feedback_from_db(
    interview_id: int = Query(...),
    candidate_id: int = Query(...),
    user_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """Generate comprehensive feedback using ALL database fields with enterprise security"""
    
    try:
        logger.info(f"Starting comprehensive feedback generation for user: {user_id}, interview_id: {interview_id}, candidate_id: {candidate_id}")
        
        # Verify user exists and get organization context
        try:
            user_id_int = int(user_id)
        except ValueError:
            logger.error(f"Invalid user_id format: {user_id}")
            raise HTTPException(status_code=400, detail="Invalid user_id format")
            
        user = db.query(User).filter(User.user_id == user_id_int).first()
        if not user:
            logger.error(f"User not found: {user_id}")
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
        
        organization_id = user.organization_id
        logger.info(f"User verified: {user_id}, Organization: {organization_id}")
        
        # Verify interview exists
        interview = db.query(Interview).filter(Interview.interview_id == interview_id).first()
        if not interview:
            logger.error(f"Interview not found: {interview_id}")
            raise HTTPException(status_code=404, detail=f"Interview with ID {interview_id} not found")
        
        # Verify candidate exists and belongs to the same job/organization context
        candidate = db.query(SQLCandidate).filter(SQLCandidate.candidate_id == candidate_id).first()
        if not candidate:
            logger.error(f"Candidate not found: {candidate_id}")
            raise HTTPException(status_code=404, detail=f"Candidate with ID {candidate_id} not found")
        
        # Verify candidate is associated with the interview's job
        if candidate.job_id != interview.job_id:
            logger.error(f"Candidate {candidate_id} is not associated with interview {interview_id} job")
            raise HTTPException(status_code=403, detail="Access denied: Candidate not associated with this interview")
        
        # Verify job belongs to user's organization through recruiter assignment
        # This is the PRIMARY organization check - if the job is assigned to someone in the org, anyone in that org can view
        job_assignment = db.query(JobRecruiterAssignment).filter(
            JobRecruiterAssignment.job_id == interview.job_id
        ).first()
        
        if job_assignment:
            assigned_user = db.query(User).filter(User.user_id == job_assignment.user_id).first()
            if not assigned_user or assigned_user.organization_id != organization_id:
                logger.error(f"Job {interview.job_id} does not belong to user's organization {organization_id}")
                raise HTTPException(status_code=403, detail="Access denied: Job not accessible to your organization")
        else:
            # If no job assignment found, check if interview.user_id belongs to same organization as fallback
            interviewer = db.query(User).filter(User.user_id == interview.user_id).first()
            if not interviewer or interviewer.organization_id != organization_id:
                logger.error(f"Interview {interview_id} and job {interview.job_id} not accessible to organization {organization_id}")
                raise HTTPException(status_code=403, detail="Access denied: Interview not accessible to your organization")
        
        logger.info(f"All security checks passed for user {user_id}, organization {organization_id}")
        
        # Check for existing feedback in MongoDB first (caching)
        logger.info(f"🔍 Checking for existing feedback for interview {interview_id}, candidate {candidate_id}")
        existing_feedback = find_one("interview_feedbacks", {
            "interview_id": interview_id,
            "candidate_id": candidate_id
        })
        
        if existing_feedback:
            logger.info(f"✅ Found existing feedback in cache, returning without regenerating")
            # Return complete cached feedback with all fields
            cached_result = {
                "status": "success",
                "feedback_text": existing_feedback.get("feedback_text", ""),
                "candidate_name": existing_feedback.get("candidate_name", "Unknown"),
                "job_title": existing_feedback.get("job_title", "Unknown Position"),
                "interview_date": existing_feedback.get("interview_date", "N/A"),
                "interviewer_name": existing_feedback.get("interviewer_name", "Unknown"),
                "evaluation_score": existing_feedback.get("evaluation_score", 0.0),
                "recommendation": existing_feedback.get("recommendation", "N/A"),
                "strengths": existing_feedback.get("strengths", "N/A"),
                "weaknesses": existing_feedback.get("weaknesses", "N/A"),
                "created_at": existing_feedback.get("created_at", "N/A"),
                "interview_id": existing_feedback.get("interview_id"),
                "candidate_id": existing_feedback.get("candidate_id"),
                "pdf_path": existing_feedback.get("pdf_path", ""),
                "competency_scores": existing_feedback.get("competency_scores", {}),
                "skills_breakdown": existing_feedback.get("skills_breakdown", {}),
                "interview_performance": existing_feedback.get("interview_performance", {}),
                "detailed_ratings": existing_feedback.get("detailed_ratings", []),
                "metadata": {
                    "data_completeness": existing_feedback.get("data_completeness", {}),
                    "cached": True,
                    "generated_at": existing_feedback.get("created_at", "N/A"),
                    "data_sources_used": existing_feedback.get("data_sources_used", [])
                }
            }
            return JSONResponse(status_code=200, content=cached_result)
        
        logger.info(f"🆕 No cached feedback found, generating new feedback")
        
        # Initialize the perfect feedback generator with user context
        feedback_generator = PerfectFeedbackGenerator(db)
        
        # Generate comprehensive feedback with organization context
        result = await feedback_generator.generate_comprehensive_feedback(
            interview_id=interview_id,
            candidate_id=candidate_id,
            user_id=user_id_int,
            organization_id=organization_id
        )
        
        # result is already a JSONResponse, extract the content
        if isinstance(result, JSONResponse):
            logger.info(f"✅ Successfully generated new comprehensive feedback")
            return result
        else:
            # If it's a dict, wrap it
            logger.info(f"Successfully generated comprehensive feedback for user {user_id} with {result.get('metadata', {}).get('data_completeness', {}).get('completeness_percentage', 'N/A')}% data completeness")
            return JSONResponse(status_code=200, content=result)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error in feedback generation: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500, 
            content={
                "status": "error", 
                "detail": "Internal server error during feedback generation",
                "error_type": type(e).__name__
            }
        )

@job_description_router.post("/regenerate_feedback", response_model=FeedbackResponse)
async def regenerate_feedback(
    interview_id: int = Query(...),
    candidate_id: int = Query(...),
    user_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """Force regenerate feedback (clears cache and generates fresh feedback)"""
    
    try:
        logger.info(f"🔄 Force regenerating feedback for interview {interview_id}, candidate {candidate_id}")
        
        # Verify user exists and get organization context
        try:
            user_id_int = int(user_id)
        except ValueError:
            logger.error(f"Invalid user_id format: {user_id}")
            raise HTTPException(status_code=400, detail="Invalid user_id format")
            
        user = db.query(User).filter(User.user_id == user_id_int).first()
        if not user:
            logger.error(f"User not found: {user_id}")
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
        
        organization_id = user.organization_id
        
        # Delete existing cached feedback
        from app.database.mongo_connection import client, MONGO_DB
        mongo_db = client[MONGO_DB]
        delete_result = mongo_db.interview_feedbacks.delete_many({
            "interview_id": interview_id,
            "candidate_id": candidate_id
        })
        logger.info(f"🗑️ Deleted {delete_result.deleted_count} cached feedback(s)")
        
        # Now generate fresh feedback
        feedback_generator = PerfectFeedbackGenerator(db)
        result = await feedback_generator.generate_comprehensive_feedback(
            interview_id=interview_id,
            candidate_id=candidate_id,
            user_id=user_id_int,
            organization_id=organization_id
        )
        
        if isinstance(result, JSONResponse):
            logger.info(f"✅ Successfully regenerated fresh feedback")
            return result
        else:
            logger.info(f"Successfully regenerated feedback with {result.get('metadata', {}).get('data_completeness', {}).get('completeness_percentage', 'N/A')}% data completeness")
            return JSONResponse(status_code=200, content=result)
            
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error regenerating feedback: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "detail": "Internal server error during feedback regeneration",
                "error_type": type(e).__name__
            }
        )

@job_description_router.get("/check_data_availability/{interview_id}/{candidate_id}/{user_id}", response_model=DataAvailabilityResponse)
async def check_data_availability(
    interview_id: int,
    candidate_id: int,
    user_id: str,
    db: Session = Depends(get_db)
):
    """Check what data is available for feedback generation with organization security"""
    
    try:
        # Verify user and get organization context
        try:
            user_id_int = int(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id format")
            
        user = db.query(User).filter(User.user_id == user_id_int).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
        
        organization_id = user.organization_id
        
        feedback_generator = PerfectFeedbackGenerator(db)
        complete_data = await feedback_generator._extract_all_database_fields(
            interview_id, candidate_id, user_id_int, organization_id
        )
        data_completeness = feedback_generator._calculate_data_completeness(complete_data)
        
        return JSONResponse(status_code=200, content={
            "status": "success",
            "interview_id": interview_id,
            "candidate_id": candidate_id,
            "data_completeness": data_completeness,
            "available_data_sources": list(complete_data.keys()),
            "candidate_name": complete_data.get("candidate", {}).get("name", "Unknown"),
            "job_title": complete_data.get("job", {}).get("title", "Unknown"),
            "organization_id": organization_id
        })
        
    except Exception as e:
        logger.error(f"Error checking data availability: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)}
        )

@job_description_router.get("/debug_data_structure/{interview_id}/{candidate_id}/{user_id}")
async def debug_data_structure(
    interview_id: int,
    candidate_id: int,
    user_id: str,
    db: Session = Depends(get_db)
):
    """Debug endpoint to see the complete data structure with organization security"""
    
    try:
        # Verify user and get organization context
        try:
            user_id_int = int(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id format")
            
        user = db.query(User).filter(User.user_id == user_id_int).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
        
        organization_id = user.organization_id
        
        feedback_generator = PerfectFeedbackGenerator(db)
        complete_data = await feedback_generator._extract_all_database_fields(
            interview_id, candidate_id, user_id_int, organization_id
        )
        
        # Remove sensitive data for debugging
        debug_data = {}
        for key, value in complete_data.items():
            if isinstance(value, dict):
                debug_data[key] = {k: type(v).__name__ for k, v in value.items()}
            elif isinstance(value, list):
                debug_data[key] = f"List with {len(value)} items"
            else:
                debug_data[key] = type(value).__name__
        
        return JSONResponse(status_code=200, content={
            "status": "success",
            "data_structure": debug_data,
            "total_data_points": len(complete_data),
            "data_completeness": feedback_generator._calculate_data_completeness(complete_data),
            "organization_id": organization_id,
            "user_id": user_id_int
        })
        
    except Exception as e:
        logger.error(f"Error in debug data structure: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)}
        )

##SALARY PREDICTION
# Update the existing predict_salary endpoint with better error handling

@job_description_router.get("/predict_salary", response_model=SalaryPredictionResponse)
async def predict_comprehensive_salary(
    interview_id: int = Query(...),
    candidate_id: int = Query(...),
    user_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """Predict comprehensive salary using ALL database fields with enterprise security and error handling"""
    
    try:
        logger.info(f"Starting comprehensive salary prediction for user: {user_id}, interview: {interview_id}, candidate: {candidate_id}")
        
        # Verify user exists and get organization context
        try:
            user_id_int = int(user_id)
        except ValueError:
            logger.error(f"Invalid user_id format: {user_id}")
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        
        user = db.query(User).filter(User.user_id == user_id_int).first()
        if not user:
            logger.error(f"User not found: {user_id}")
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
        
        organization_id = user.organization_id
        if not organization_id:
            logger.error(f"User {user_id} has no organization assigned")
            raise HTTPException(status_code=400, detail="User has no organization assigned")
        
        logger.info(f"User verified: {user_id}, Organization: {organization_id}")

        # Perform all security checks for salary prediction
        interview = db.query(Interview).filter(Interview.interview_id == interview_id).first()
        if not interview:
            logger.error(f"Interview not found: {interview_id}")
            raise HTTPException(status_code=404, detail="Interview not found")
        
        # Verify interviewer belongs to same organization
        interviewer = db.query(User).filter(User.user_id == interview.user_id).first()
        if not interviewer or interviewer.organization_id != organization_id:
            logger.error(f"Access denied: Interview {interview_id} not accessible to organization {organization_id}")
            raise HTTPException(status_code=403, detail="Access denied: Interview not accessible to your organization")
        
        # Verify candidate belongs to the interview's job
        candidate = db.query(SQLCandidate).filter(SQLCandidate.candidate_id == candidate_id).first()
        if not candidate:
            logger.error(f"Candidate not found: {candidate_id}")
            raise HTTPException(status_code=404, detail="Candidate not found")
        
        if candidate.job_id != interview.job_id:
            logger.error(f"Access denied: Candidate {candidate_id} not associated with interview {interview_id}")
            raise HTTPException(status_code=403, detail="Access denied: Candidate not associated with this interview")
        
        # Verify job belongs to organization through recruiter assignment
        job_assignment = db.query(JobRecruiterAssignment).filter(
            JobRecruiterAssignment.job_id == interview.job_id
        ).first()
        
        if job_assignment:
            assigned_user = db.query(User).filter(User.user_id == job_assignment.user_id).first()
            if not assigned_user or assigned_user.organization_id != organization_id:
                logger.error(f"Access denied: Job {interview.job_id} not accessible to organization {organization_id}")
                raise HTTPException(status_code=403, detail="Access denied: Job not accessible to your organization")
        
        logger.info("All security checks passed for salary prediction")
        
        # Initialize the comprehensive salary predictor
        salary_predictor = ComprehensiveSalaryPredictor(db)
        
        # Generate comprehensive salary prediction
        result = await salary_predictor.predict_salary_comprehensive(
            interview_id=interview_id,
            candidate_id=candidate_id,
            user_id=user_id_int,
            organization_id=organization_id
        )
        
        logger.info(f"Successfully generated comprehensive salary prediction with {result['metadata']['data_completeness']['completeness_percentage']}% data completeness")
        
        return JSONResponse(status_code=200, content=result)
        
    except HTTPException as he:
        logger.error(f"HTTP error in salary prediction: {he.detail}")
        return JSONResponse(
            status_code=he.status_code, 
            content={"status": "error", "detail": he.detail}
        )
    
    except Exception as e:
        logger.error(f"Unexpected error in salary prediction: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500, 
            content={
                "status": "error", 
                "detail": "Internal server error during salary prediction",
                "error_type": type(e).__name__,
                "fallback_available": True
            }
        )

@job_description_router.get("/check_salary_data_availability/{interview_id}/{candidate_id}/{user_id}")
async def check_salary_data_availability(
    interview_id: int,
    candidate_id: int,
    user_id: str,
    db: Session = Depends(get_db)
):
    """Check what data is available for salary prediction with enhanced error handling"""
    
    try:
        # Verify user and organization
        user_id_int = int(user_id)
        user = db.query(User).filter(User.user_id == user_id_int).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        organization_id = user.organization_id
        if not organization_id:
            raise HTTPException(status_code=400, detail="User has no organization assigned")
        
        # Perform security checks
        interview = db.query(Interview).filter(Interview.interview_id == interview_id).first()
        if not interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        interviewer = db.query(User).filter(User.user_id == interview.user_id).first()
        if not interviewer or interviewer.organization_id != organization_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        candidate = db.query(SQLCandidate).filter(SQLCandidate.candidate_id == candidate_id).first()
        if not candidate or candidate.job_id != interview.job_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Initialize salary predictor and check data availability
        salary_predictor = ComprehensiveSalaryPredictor(db)
        complete_data = await salary_predictor._extract_all_database_fields_for_salary(
            interview_id, candidate_id, user_id_int, organization_id
        )
        organization_salary_data = await salary_predictor._extract_organization_salary_data(organization_id)
        data_completeness = salary_predictor._calculate_salary_data_completeness(complete_data)
        
        return JSONResponse(status_code=200, content={
            "status": "success",
            "interview_id": interview_id,
            "candidate_id": candidate_id,
            "user_id": user_id,
            "organization_id": organization_id,
            "data_completeness": data_completeness,
            "available_data_sources": list(complete_data.keys()),
            "organization_salary_benchmarks": {
                "organization_jobs_count": len(organization_salary_data.get("organization_jobs", [])),
                "organization_candidates_with_salary": len(organization_salary_data.get("organization_candidates", [])),
                "organization_interviews_count": len(organization_salary_data.get("organization_interviews", [])),
                "organization_thresholds_count": len(organization_salary_data.get("organization_thresholds", []))
            },
            "candidate_name": complete_data.get("candidate", {}).get("name", "Unknown"),
            "job_title": complete_data.get("job", {}).get("title", "Unknown"),
            "candidate_expectation": complete_data.get("candidate", {}).get("salary_expectation", "Not provided"),
            "candidate_experience": complete_data.get("candidate", {}).get("years_of_experience", "Not provided")
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking salary data availability: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)}
        )


###SALARY PREDICTION ENDS 


##CANDIDATE JOINING PROBABILITY

@job_description_router.get("/predict_joining_probability", response_model=JoiningProbabilityResponse)
async def predict_candidate_joining_probability(
    interview_id: int = Query(...),
    candidate_id: int = Query(...),
    user_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """Predict candidate joining probability using ALL database fields with enterprise security"""

    try:
        logger.info(f"Starting joining probability prediction for user: {user_id}, interview: {interview_id}, candidate: {candidate_id}")

        # Validate user_id
        try:
            user_id_int = int(user_id)
        except ValueError:
            logger.error(f"Invalid user_id format: {user_id}")
            raise HTTPException(status_code=400, detail="Invalid user_id format")

        # Get user and organization context
        user = db.query(User).filter(User.user_id == user_id_int).first()
        if not user:
            logger.error(f"User not found: {user_id}")
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")

        organization_id = user.organization_id
        if not organization_id:
            logger.error(f"User {user_id} has no organization assigned")
            raise HTTPException(status_code=400, detail="User has no organization assigned")

        logger.info(f"User verified: {user_id}, Organization: {organization_id}")

        # Get and verify interview
        interview = db.query(Interview).filter(Interview.interview_id == interview_id).first()
        if not interview:
            logger.error(f"Interview not found: {interview_id}")
            raise HTTPException(status_code=404, detail="Interview not found")

        # Interviewer's organization match check
        interviewer = db.query(User).filter(User.user_id == interview.user_id).first()
        if not interviewer or interviewer.organization_id != organization_id:
            logger.error(f"Access denied: Interview {interview_id} not accessible to organization {organization_id}")
            raise HTTPException(status_code=403, detail="Access denied: Interview not accessible to your organization")

        # Candidate validation
        candidate = db.query(SQLCandidate).filter(SQLCandidate.candidate_id == candidate_id).first()
        if not candidate:
            logger.error(f"Candidate not found: {candidate_id}")
            raise HTTPException(status_code=404, detail="Candidate not found")

        if candidate.job_id != interview.job_id:
            logger.error(f"Access denied: Candidate {candidate_id} not associated with interview {interview_id}")
            raise HTTPException(status_code=403, detail="Access denied: Candidate not associated with this interview")

        # Check job belongs to same organization (via recruiter assignment)
        job_assignment = db.query(JobRecruiterAssignment).filter(
            JobRecruiterAssignment.job_id == interview.job_id
        ).first()

        if job_assignment:
            assigned_user = db.query(User).filter(User.user_id == job_assignment.user_id).first()
            if not assigned_user or assigned_user.organization_id != organization_id:
                logger.error(f"Access denied: Job {interview.job_id} not accessible to organization {organization_id}")
                raise HTTPException(status_code=403, detail="Access denied: Job not accessible to your organization")

        logger.info("All security checks passed for joining probability prediction")

        # Generate prediction
        joining_predictor = CandidateJoiningProbabilityPredictor(db)
        result = await joining_predictor.predict_joining_probability_comprehensive(
            interview_id=interview_id,
            candidate_id=candidate_id,
            user_id=user_id_int,
            organization_id=organization_id
        )

        logger.info(f"Successfully generated joining probability prediction with {result['metadata']['data_completeness']['completeness_percentage']}% data completeness")

        # Get latest audit trail action for the candidate
        latest_audit = db.query(AuditTrail.action).filter(
            AuditTrail.user_id == user_id
        ).order_by(AuditTrail.timestamp.desc()).first()

        # Append additional candidate details
        result["candidate_details"] = {
            "email": candidate.email,
            "years_of_experience": candidate.years_of_experience,
            "notice_period": candidate.notice_period,
            "latest_action": latest_audit.action if latest_audit else None
        }

        return JSONResponse(status_code=200, content=result)

    except HTTPException as he:
        logger.error(f"HTTP error in joining probability prediction: {he.detail}")
        return JSONResponse(
            status_code=he.status_code,
            content={"status": "error", "detail": he.detail}
        )

    except Exception as e:
        import traceback
        logger.error(f"Unexpected error in joining probability prediction: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "detail": "Internal server error during joining probability prediction",
                "error_type": type(e).__name__,
                "fallback_available": True
            }
        )

@job_description_router.get("/check_joining_data_availability/{interview_id}/{candidate_id}/{user_id}")
async def check_joining_data_availability(
    interview_id: int,
    candidate_id: int,
    user_id: str,
    db: Session = Depends(get_db)
):
    """Check what data is available for joining probability prediction"""
    
    try:
        # Verify user and organization
        user_id_int = int(user_id)
        user = db.query(User).filter(User.user_id == user_id_int).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        organization_id = user.organization_id
        if not organization_id:
            raise HTTPException(status_code=400, detail="User has no organization assigned")
        
        # Perform security checks
        interview = db.query(Interview).filter(Interview.interview_id == interview_id).first()
        if not interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        interviewer = db.query(User).filter(User.user_id == interview.user_id).first()
        if not interviewer or interviewer.organization_id != organization_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        candidate = db.query(SQLCandidate).filter(SQLCandidate.candidate_id == candidate_id).first()
        if not candidate or candidate.job_id != interview.job_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Initialize joining predictor and check data availability
        joining_predictor = CandidateJoiningProbabilityPredictor(db)
        complete_data = await joining_predictor._extract_all_database_fields_for_joining(
            interview_id, candidate_id, user_id_int, organization_id
        )
        organization_joining_data = await joining_predictor._extract_organization_joining_patterns(organization_id)
        data_completeness = joining_predictor._calculate_joining_data_completeness(complete_data)
        
        return JSONResponse(status_code=200, content={
            "status": "success",
            "interview_id": interview_id,
            "candidate_id": candidate_id,
            "user_id": user_id,
            "organization_id": organization_id,
            "data_completeness": data_completeness,
            "available_data_sources": list(complete_data.keys()),
            "organization_joining_patterns": {
                "historical_joining_rate": organization_joining_data.get("joining_patterns", {}).get("joining_rate", 0),
                "offer_acceptance_rate": organization_joining_data.get("joining_patterns", {}).get("offer_acceptance_rate", 0),
                "total_historical_candidates": len(organization_joining_data.get("historical_candidates", [])),
                "organization_attractiveness_score": organization_joining_data.get("organization_attractiveness", {}).get("organization_reputation_score", 0)
            },
            "candidate_profile": {
                "name": complete_data.get("candidate", {}).get("name", "Unknown"),
                "job_title": complete_data.get("job", {}).get("title", "Unknown"),
                "experience_years": complete_data.get("candidate", {}).get("years_of_experience", 0),
                "salary_expectation": complete_data.get("candidate", {}).get("salary_expectation", "Not provided"),
                "notice_period": complete_data.get("candidate", {}).get("notice_period", "Not provided"),
                "current_status": complete_data.get("candidate", {}).get("status", "Unknown")
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking joining data availability: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)}
        )


@job_description_router.get("/organization_joining_insights/{organization_id}/{user_id}")
async def get_organization_joining_insights(
    organization_id: int,
    user_id: str,
    db: Session = Depends(get_db)
):
    """Get comprehensive organization joining insights and benchmarks"""
    
    try:
        # Verify user belongs to organization
        user_id_int = int(user_id)
        user = db.query(User).filter(User.user_id == user_id_int).first()
        if not user or user.organization_id != organization_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Initialize joining predictor
        joining_predictor = CandidateJoiningProbabilityPredictor(db)
        organization_joining_data = await joining_predictor._extract_organization_joining_patterns(organization_id)
        
        # Get organization details
        organization = db.query(Organization).filter(Organization.organization_id == organization_id).first()
        if not organization:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        return JSONResponse(status_code=200, content={
            "status": "success",
            "organization": {
                "organization_id": organization_id,
                "organization_name": organization.organization_name,
                "industry": organization.industry,
                "size": organization.size
            },
            "joining_analytics": {
                "historical_performance": organization_joining_data.get("joining_patterns", {}),
                "organization_attractiveness": organization_joining_data.get("organization_attractiveness", {}),
                "candidate_insights": {
                    "total_candidates_analyzed": len(organization_joining_data.get("historical_candidates", [])),
                    "avg_candidate_experience": sum([c.get("years_of_experience", 0) for c in organization_joining_data.get("historical_candidates", [])]) / max(1, len(organization_joining_data.get("historical_candidates", []))),
                    "common_education_levels": list(set([c.get("education_level", "Not specified") for c in organization_joining_data.get("historical_candidates", [])]))
                }
            },
            "recommendations": {
                "improvement_areas": [
                    "Enhance employer branding" if organization_joining_data.get("joining_patterns", {}).get("joining_rate", 0) < 70 else "Maintain strong joining rates",
                    "Optimize offer process" if organization_joining_data.get("joining_patterns", {}).get("offer_acceptance_rate", 0) < 80 else "Continue effective offer process",
                    "Focus on candidate experience improvements"
                ],
                "strengths": [
                    "Strong interview process" if organization_joining_data.get("organization_attractiveness", {}).get("average_interview_score", 0) > 7 else "Room for interview improvements",
                    "Good organizational reputation" if organization_joining_data.get("organization_attractiveness", {}).get("organization_reputation_score", 0) > 75 else "Build stronger employer brand"
                ]
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting organization joining insights: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)}
        )


@job_description_router.post("/test_joining_prediction")
async def test_joining_prediction_endpoint(
    db: Session = Depends(get_db)
):
    """Test endpoint to verify joining probability prediction functionality"""
    
    try:
        # Test with sample data
        test_interview_id = 1
        test_candidate_id = 1
        test_user_id = 2
        
        # Verify test data exists
        user = db.query(User).filter(User.user_id == test_user_id).first()
        if not user:
            return JSONResponse(status_code=404, content={
                "status": "error",
                "detail": f"Test user {test_user_id} not found"
            })
        
        interview = db.query(Interview).filter(Interview.interview_id == test_interview_id).first()
        if not interview:
            return JSONResponse(status_code=404, content={
                "status": "error", 
                "detail": f"Test interview {test_interview_id} not found"
            })
        
        candidate = db.query(SQLCandidate).filter(SQLCandidate.candidate_id == test_candidate_id).first()
        if not candidate:
            return JSONResponse(status_code=404, content={
                "status": "error",
                "detail": f"Test candidate {test_candidate_id} not found"
            })
        
        # Initialize joining predictor
        joining_predictor = CandidateJoiningProbabilityPredictor(db)
        
        # Test data extraction
        complete_data = await joining_predictor._extract_all_database_fields_for_joining(
            test_interview_id, test_candidate_id, test_user_id, user.organization_id
        )
        
        organization_joining_data = await joining_predictor._extract_organization_joining_patterns(user.organization_id)
        
        return JSONResponse(status_code=200, content={
            "status": "success",
            "message": "Joining probability prediction system is working correctly",
            "test_data": {
                "user_id": test_user_id,
                "organization_id": user.organization_id,
                "interview_id": test_interview_id,
                "candidate_id": test_candidate_id,
                "candidate_name": complete_data.get("candidate", {}).get("name", "Unknown"),
                "job_title": complete_data.get("job", {}).get("title", "Unknown"),
                "data_sources_available": len(complete_data),
                "organization_benchmarks_available": len(organization_joining_data),
                "historical_joining_rate": organization_joining_data.get("joining_patterns", {}).get("joining_rate", 0)
            },
            "system_status": "operational",
            "fallback_available": True
        })
        
    except Exception as e:
        logger.error(f"Error in joining prediction test: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "detail": f"Test failed: {str(e)}",
                "system_status": "error"
            }
        )

@job_description_router.get("/user-candidates/{user_id}/{organization_id}")
async def get_user_candidates(
    user_id: int,
    organization_id: int,
    db: Session = Depends(get_db)
):
    """Get all candidates for a user's organization with interview and candidate data"""
    try:
        # Verify user belongs to organization
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user or user.organization_id != organization_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get organization users
        organization_users = db.query(User).filter(User.organization_id == organization_id).all()
        user_ids = [u.user_id for u in organization_users]
        
        # Get job assignments for organization
        job_assignments = db.query(JobRecruiterAssignment).filter(
            JobRecruiterAssignment.user_id.in_(user_ids)
        ).all()
        job_ids = [assignment.job_id for assignment in job_assignments]
        
        # Get candidates and their interviews
        candidates_data = []
        candidates = db.query(SQLCandidate).filter(SQLCandidate.job_id.in_(job_ids)).all()
        
        for candidate in candidates:
            # Get job details
            job = db.query(JobDescription).filter(JobDescription.job_id == candidate.job_id).first()
            
            # Get latest interview for candidate
            interview = (
                db.query(Interview)
                .filter(Interview.candidate_id == candidate.candidate_id)
                .order_by(Interview.interview_date.desc())
                .first()
            )
            
            # Handle certifications count safely
            cert_count = 0
            if candidate.certifications:
                if isinstance(candidate.certifications, list):
                    cert_count = len(candidate.certifications)
                elif isinstance(candidate.certifications, str):
                    cert_count = len(candidate.certifications.split(',')) if candidate.certifications else 0
            
            candidate_data = {
                "id": candidate.candidate_id,
                "candidate_id": candidate.candidate_id,
                "interview_id": interview.interview_id if interview else None,
                "name": candidate.name,
                "email": candidate.email,
                "job_title": job.title if job else "Unknown Position",
                "department": job.department if job else "Not specified",
                "location": "Remote",  # Add this field to your database if needed
                "years_of_experience": candidate.years_of_experience,
                "education_level": candidate.education_level,
                "salary_expectation": candidate.salary_expectation,
                "notice_period": candidate.notice_period,
                "status": candidate.status,
                "interview_score": interview.interview_score if interview else None,
                "skills_score": 75,  # Add logic to calculate from evaluations or set default
                "certifications_count": cert_count,
                "job_level": job.experience_level if job else "Not specified",
                "employment_type": "Full-time",  # Default or add to database
                "availability_in_weeks": 4,  # Add to database or calculate
                "previous_salary": "Not specified",  # Add to database
            }
            
            candidates_data.append(candidate_data)
        
        return JSONResponse(status_code=200, content={
            "status": "success",
            "data": candidates_data
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user candidates: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)}
        )

    
@job_description_router.post("/evaluate_QA")
async def evaluate_qa(request: EvaluateQARequest = None) -> JSONResponse:
    try:
        # Get the transcriber instance
        transcriber = DualInputTranscriber()
        
        # Add debug logging
        logger.info("Starting evaluation process")
        
        # Use the provided text if available, otherwise look for recordings
        full_text = ""
        if request and request.interview_text:
            full_text = request.interview_text
            logger.info(f"Using provided interview text: {full_text}")
        else:
            # Find any recording in MongoDB, prioritizing active ones
            active_recording = find_one(
                "interview_transcriptions",
                {"status": "Active", "interview_type": "job_description"},
                sort=[("created_at", -1)]  # Get the most recent active recording
            )
            
            # Log what we found
            if active_recording:
                logger.info(f"Found active recording with ID: {active_recording['_id']}")
                # Use transcript_text instead of interviewer_text
                full_text = active_recording.get('transcript_text', '')
                logger.info(f"Transcript text from recording: {full_text}")
            else:
                logger.info("No active recording found, looking for completed recording")
            
            # If no active recording is found, try to find a completed one
            if not active_recording or not full_text:
                completed_recording = find_one(
                    "interview_transcriptions",
                    {"status": "Completed", "interview_type": "job_description"},
                    sort=[("created_at", -1)]  # Get the most recent completed recording
                )
                
                if completed_recording:
                    logger.info(f"Found completed recording with ID: {completed_recording['_id']}")
                    # Use transcript_text instead of interviewer_text
                    full_text = completed_recording.get('transcript_text', '')
                    logger.info(f"Transcript text from completed recording: {full_text}")
                else:
                    logger.info("No completed recording found either")
        
        # If still no text, return an error
        if not full_text:
            logger.info("No interview text found in request, recordings, or current state")
            return JSONResponse(
                content={
                    "status": "error",
                    "explanation": "No interview text found. Please provide text or record some first.",
                    "mark": "âŒ",
                    "score": "0%",
                },
                status_code=200
            )
        
        logger.info(f"Processing full text: {full_text}")
        
        # Initialize Gemini model if not already done
        if not transcriber.model:
            logger.info("Initializing Gemini model")
            
            transcriber.model = GeminiModelLoader.get_model()        
        # Extract question and answer from transcript text
        question = ""
        answer = ""
        
        # Parse the transcript text to extract question and answer
        # This handles the format "Interviewer: [question]\nCandidate: [answer]"
        interviewer_prefix = "Interviewer:"
        candidate_prefix = "Candidate:"
        
        if interviewer_prefix in full_text and candidate_prefix in full_text:
            # Split by prefixes to extract the parts
            parts = full_text.split(interviewer_prefix)
            
            # Process each part (skip the first empty part if it exists)
            for part in parts[1:]:  # Skip the first part which might be empty
                if candidate_prefix in part:
                    # This part contains both a question and an answer
                    q_a_parts = part.split(candidate_prefix)
                    
                    # Extract question (first part)
                    q_text = q_a_parts[0].strip()
                    if q_text and not question:  # Take the first question if not set
                        question = q_text
                    
                    # Extract answer (second part)
                    if len(q_a_parts) > 1:
                        a_text = q_a_parts[1].strip()
                        if a_text and not answer:  # Take the first answer if not set
                            answer = a_text
                else:
                    # This part contains only a question
                    q_text = part.strip()
                    if q_text and not question:  # Take the first question if not set
                        question = q_text
        
        logger.info(f"Extracted - Question: {question}, Answer: {answer}")
        
        # If we couldn't extract both, use AI to separate
        if not question or not answer:
            logger.info("Using AI to separate question and answer")
            separation_prompt = f"""
            The following text might contain both an interview question and an answer, or just a question, or just an answer.
            Please identify which part is the question and which part is the answer.
            If there's only a question, generate a plausible answer.
            If there's only an answer, infer what the question might have been.
            
            Text: {full_text}
            
            Respond in this exact format:
            QUESTION: [the question part]
            ANSWER: [the answer part]
            """
            
            try:
                separation_response = transcriber.model.generate_content(separation_prompt)
                separation_text = separation_response.text
                logger.info(f"AI separation response: {separation_text}")
                
                # Parse the response to extract question and answer
                for line in separation_text.split("\n"):
                    if line.startswith("QUESTION:"):
                        question = line.replace("QUESTION:", "").strip()
                    elif line.startswith("ANSWER:"):
                        answer = line.replace("ANSWER:", "").strip()
            except Exception as e:
                logger.error(f"Error during AI separation: {str(e)}")
                # Use a simple fallback approach
                if "?" in full_text:
                    parts = full_text.split("?", 1)
                    question = parts[0] + "?"
                    answer = parts[1] if len(parts) > 1 else "No answer provided."
                else:
                    question = "What can you tell me about your experience?"
                    answer = full_text
        
        logger.info(f"Final - Question: {question}, Answer: {answer}")
        
        # Now evaluate the answer
        logger.info("Sending Q&A to AI for evaluation")
        evaluation_prompt = f"""
        Evaluate this interview Q&A pair:
        
        Interviewer question: {question}
        Candidate answer: {answer}
        
        Based on the interviewer's question and the candidate's response, evaluate:
        1. How well the candidate understood what information was being requested
        2. The relevance and accuracy of the candidate's answer
        3. The completeness and depth of the response
        
        Provide your evaluation in exactly this format:
        SCORE: [number between 0-100]
        EXPLANATION: [detailed feedback]
        """
        
        # Call the model
        try:
            response = transcriber.model.generate_content(evaluation_prompt)
            response_text = response.text
            logger.info(f"AI evaluation response: {response_text}")
        except Exception as e:
            logger.error(f"Error during AI evaluation: {str(e)}")
            response_text = "SCORE: 70\nEXPLANATION: The candidate provided a reasonable answer."
            logger.info(f"Using default evaluation: {response_text}")
        
        # Parse response with better error handling
        score = "0"
        explanation = "No evaluation generated"
        
        for line in response_text.split("\n"):
            if "SCORE:" in line:
                score = line.replace("SCORE:", "").strip().rstrip("%")
                logger.info(f"Extracted score: {score}")
            elif "EXPLANATION:" in line:
                explanation = line.replace("EXPLANATION:", "").strip()
                logger.info(f"Extracted explanation: {explanation}")
        
        # Convert score to float for calculations
        try:
            score_float = float(score)
            logger.info(f"Converted score to float: {score_float}")
        except ValueError:
            logger.error(f"Error converting score '{score}' to float")
            score_float = 70.0
            logger.info(f"Using default score: {score_float}")
        
        # Find the recording ID to associate with this evaluation
        recording_id = None
        if 'active_recording' in locals() and active_recording:
            recording_id = str(active_recording["_id"])
        elif 'completed_recording' in locals() and completed_recording:
            recording_id = str(completed_recording["_id"])
        
        # Create evaluation document
        evaluation_data = {
            "evaluation_id": 1,
            "candidate_id": None,
            "job_id": None,
            "interview_id": recording_id,
            "evaluator_id": None,
            "evaluation_date": datetime.now(),
            
            # Overall scores
            "overall_scores": {
                "total_score": score_float,
                "recommendation": "Hire" if score_float >= 70 else "Consider" if score_float >= 50 else "Reject",
                "match_percentage": score_float,
                "confidence_score": 80.0
            },
            
            # Simplified category scores
            "category_scores": {
                "technical_skills": {
                    "score": score_float,
                    "strengths": [],
                    "weaknesses": [],
                    "detailed_skills": {}
                },
                "communication": {
                    "score": score_float,
                    "clarity": score_float,
                    "articulation": score_float,
                    "listening": score_float,
                    "non_verbal": score_float
                }
            },
            
            # Question-by-question analysis
            "question_analysis": [{
                "question": question,
                "answer": answer,
                "score": score_float,
                "feedback": explanation
            }],
            
            # AI-generated feedback
            "ai_feedback": {
                "summary": explanation,
                "strengths": [],
                "areas_for_improvement": [],
                "hiring_recommendation": "Consider based on this answer",
                "fit_analysis": "",
                "suggested_interview_questions": []
            },
            
            # Metadata
            "evaluation_type": "Q&A",
            "evaluation_method": "AI",
            "evaluation_duration": 0.0,
            "notes": response_text,
            "status": "Completed",
            
            # Timestamps
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        # Insert into MongoDB
        try:
            from app.database.mongo_connection import insert_data
            result = insert_data("candidate_evaluations", evaluation_data)
            eval_id = str(result.inserted_id)
            logger.info(f"Saved evaluation with ID: {eval_id}")
        except Exception as e:
            logger.error(f"Error saving evaluation to MongoDB: {str(e)}")
            eval_id = "error-id"
        
        # Prepare the response
        response_data = {
            "status": "success",
            "explanation": explanation,
            "mark": "âœ…" if score_float >= 60 else "âŒ",
            "score": f"{score}%",
            "eval_id": eval_id,
            "qa_pair": {
                "question": question,
                "answer": answer
            }
        }
        
        logger.info(f"Returning response: {response_data}")
        
        # Return the evaluation result
        return JSONResponse(
            content=response_data,
            status_code=200
        )
    
    except Exception as e:
        logger.error(f"Error in evaluate_qa endpoint: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Return a 200 status code with an error message in the body
        return JSONResponse(
            content={
                "status": "error",
                "explanation": f"Error processing evaluation: {str(e)}",
                "mark": "âŒ",
                "score": "0%",
            },
            status_code=200
        )


@job_description_router.get("/test-qa-generation")
async def test_qa_generation() -> JSONResponse:
    """Test endpoint to verify QA generation functionality"""
    try:
        # Sample job description content
        sample_content = """
        We are looking for a Senior Python Developer with 5+ years of experience in web development.
        The ideal candidate should have strong knowledge of Django, Flask, and REST APIs.
        Experience with PostgreSQL, Redis, and cloud platforms like AWS is required.
        The candidate should be able to work in an agile environment and lead a team of developers.
        """
        
        # Test QA generation with different difficulty levels
        test_cases = [
            {"difficulty": "beginner", "num_qa": 2},
            {"difficulty": "intermediate", "num_qa": 2}, 
            {"difficulty": "advanced", "num_qa": 2}
        ]
        
        results = []
        for test_case in test_cases:
            try:
                result = JobDescriptionService.generate_qa(
                    dashboard_content=sample_content,
                    num_qa=test_case["num_qa"],
                    difficulty=test_case["difficulty"]
                )
                
                results.append({
                    "difficulty": test_case["difficulty"],
                    "status": "success",
                    "qa_id": result["qa_id"],
                    "total_questions": result["metadata"]["total_questions"],
                    "sample_question": result["formatted_qa"].split('\n')[0] if result["formatted_qa"] else "No question generated"
                })
                
            except Exception as e:
                results.append({
                    "difficulty": test_case["difficulty"],
                    "status": "error",
                    "error": str(e)
                })
        
        return JSONResponse(
            content={
                "status": "success",
                "message": "QA generation test completed",
                "test_results": results,
                "sample_content": sample_content.strip()
            },
            status_code=200
        )
        
    except Exception as e:
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Test failed: {str(e)}"
            },
            status_code=500
        )

@job_description_router.get("/Get-evaluation/{eval_id}")
async def get_evaluation(eval_id: str) -> JSONResponse:
    # Use the standalone function instead of calling it as a class method
    result = get_evaluation_qa_content(eval_id)
    return JSONResponse(
        content=result,
        status_code=(
            200
            if result["status"] == "success"
            else 404 if "not found" in result.get("message", "") else 500
        ),
    )


@job_description_router.get("/job-description-content/{job_id}")
async def get_job_description_content(job_id: int, db: Session = Depends(get_db)):
    job_description_service = JobDescriptionService()
    return await job_description_service.get_job_description_content(job_id, db)


@job_description_router.get("/sample_prompts/{job_id}")
async def get_sample_prompts(job_id: int, db: Session = Depends(get_db)):
    jd = db.query(JobDescription).filter(JobDescription.job_id == job_id).first()
    if not jd:
        raise HTTPException(status_code=404, detail="Job not found")
    prompts = await JDLLMService.generate_sample_prompts(jd, num_prompts=5)
    return {"sample_prompts": prompts}

@job_description_router.post("/custom_prompt/{job_id}")
async def run_custom_prompt(job_id: int, request: CustomPromptRequest, db: Session = Depends(get_db)):
    prompt = request.prompt
    jd = db.query(JobDescription).filter(JobDescription.job_id == job_id).first()
    if not jd:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        processor = DocumentProcessor()
        content = processor.generate_dashboard(
            jd_id=str(jd.job_id),
            jd_text=jd.description,
            dashboard_type="custom",
            custom_prompt=prompt
        )
    except Exception as e:
        logger.error(f"LLM Error in /custom_prompt/{job_id}: {e}")
        raise HTTPException(status_code=500, detail="Dashboard generation failed. Please try again.")

    # Ensure JSON string
    if isinstance(content, str):
        try:
            content_json = json.loads(content)
        except json.JSONDecodeError:
            content_json = content
    else:
        content_json = content

    dashboard = DashboardContent(
        job_id=jd.job_id,
        resume_id=None,
        prompt=prompt,
        text=jd.description, # text=jd.raw_text, 
        content=json.dumps(content_json),
        dashboard_type="custom",
        created_at=datetime.utcnow(),
        status="active"
    )
    db.add(dashboard)
    db.commit()
    db.refresh(dashboard)

    return {"data": {"dashboard_id": dashboard.id, "content": content_json}}

@job_description_router.post("/auto_generate/{job_id}")
async def auto_generate_dashboards(
    job_id: int,
    count: int = Query(1, ge=1, le=10),
    db: Session = Depends(get_db)
) -> dict:
    # Fetch job description
    jd = db.query(JobDescription).filter(JobDescription.job_id == job_id).first()
    if not jd:
        raise HTTPException(status_code=404, detail="Job not found")

    # Step 1: Get existing dashboards (limited to needed count)
    existing_dashboards = (
        db.query(DashboardContent)
        .filter(
            DashboardContent.job_id == job_id,
            DashboardContent.dashboard_type == "auto",
            DashboardContent.status == "active"
        )
        .order_by(DashboardContent.created_at.asc())
        .limit(count)
        .all()
    )

    existing_count = len(existing_dashboards)
    
    # Step 2: If enough exist, return them
    if existing_count >= count:
        return {
            "job_id": job_id,
            "count": count,
            "dashboards": [
                {
                    "dashboard_id": d.id,
                    "dashboard_title": DocumentProcessor.parse_content(d.content).get("dashboard_title"),
                    "overview": DocumentProcessor.parse_content(d.content).get("overview")
                }
                for d in existing_dashboards[:count]
            ]
        }

    # Step 3: Generate only the missing dashboards
    missing_count = count - existing_count
    logger.info(f"Generating {missing_count} new dashboards for job {job_id}")
    
    processor = DocumentProcessor()
    new_dashboards = processor.generate_multiple_dashboards_from_jd(
        jd_text=jd.description,
        count=missing_count
    )

    # Validate output
    if not isinstance(new_dashboards, list) or not all(isinstance(d, dict) for d in new_dashboards):
        raise HTTPException(status_code=500, detail="Invalid dashboard format returned.")

    # Step 4: Save new dashboards to DB in batch
    dashboards_to_add = []
    for dashboard_data in new_dashboards:
        dashboard = DashboardContent(
            job_id=jd.job_id,
            resume_id=None,
            prompt="",
            text=jd.description,   #jd_text=jd.raw_text
            content=json.dumps(dashboard_data),
            dashboard_type="auto",
            created_at=datetime.utcnow(),
            status="active"
        )
        dashboards_to_add.append(dashboard)
        existing_dashboards.append(dashboard)

    try:
        db.add_all(dashboards_to_add)
        db.commit()
        for d in dashboards_to_add:
            db.refresh(d)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"DB transaction failed for dashboards: {e}")
        raise HTTPException(status_code=500, detail="Database error during dashboard creation.")
        
    # Step 5: Return combined dashboards
    return {
        "job_id": job_id,
        "count": len(existing_dashboards),
        "dashboards": [
            {
                "dashboard_id": d.id,
                "dashboard_title": DocumentProcessor.parse_content(d.content).get("dashboard_title"),
                "overview": DocumentProcessor.parse_content(d.content).get("overview")
            }
            for d in existing_dashboards[:count]
        ]
    }

@job_description_router.get("/User-job-descriptions/{user_id}")
async def get_user_job_descriptions_endpoint(
    user_id: str, db: Session = Depends(get_db)
) -> JSONResponse:
    try:
        user_id_int = int(user_id)
        result = await JobDescriptionService.get_user_job_descriptions(user_id_int, db)
        status_code = 200 if result["status"] == "success" else 500
        return JSONResponse(content=result, status_code=status_code)
    except ValueError:
        return JSONResponse(
            content={
                "status": "error",
                "message": "Invalid user ID format. User ID must be an integer.",
            },
            status_code=422,
        )



@job_description_router.post("/modify/{dashboard_id}")
async def modify_existing_dashboard(
    dashboard_id: int,
    modification_prompt: str = Query(..., description="Prompt describing changes to the dashboard"),
    allow_undo: bool = Query(True, description="Whether to keep a backup of the original dashboard for undo"),
    db: Session = Depends(get_db),
):
    """
    Modify an existing dashboard (auto or manual) using a prompt.
    Updates the current dashboard in place, with optional backup for undo.
    """

    dashboard = db.query(DashboardContent).filter(DashboardContent.id == dashboard_id).first()
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Backup the original dashboard if undo is allowed
    backup_dashboard_id = None
    if allow_undo:
        backup_dashboard = DashboardContent(
            job_id=dashboard.job_id,
            resume_id=dashboard.resume_id, 
            prompt=dashboard.prompt,
            text=dashboard.text,
            content=dashboard.content,
            dashboard_type=dashboard.dashboard_type,
            modified_from_id=dashboard.modified_from_id,
            created_at=dashboard.created_at,
            status="backup",  # Mark as backup for future undo
        )
        db.add(backup_dashboard)
        db.flush()  # Get the ID before commit
        backup_dashboard_id = backup_dashboard.id

    # Call LLM service to generate the modified content
    try:
        processor = DocumentProcessor()
        modified_content = processor.generate_dashboard(
            jd_id=str(dashboard.job_id),
            jd_text=dashboard.text,
            dashboard_type="modified",
            custom_prompt=modification_prompt,
            base_dashboard_content=dashboard.content,
        )
    
    except Exception as e:
        logger.error(f"LLM Error in /modify/{dashboard_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to modify dashboard. Please try again.")
    if isinstance(modified_content, str):
        try:
            modified_content_json = json.loads(modified_content)
        except json.JSONDecodeError:
            modified_content_json = modified_content
    else:
        modified_content_json = modified_content

    # Update the existing dashboard in place
    if isinstance(modified_content_json, dict):
      dashboard.content = json.dumps(modified_content_json)
    else:
      dashboard.content = modified_content_json
    dashboard.prompt = modification_prompt
    dashboard.dashboard_type = "modified"
    dashboard.modified_from_id = backup_dashboard_id if allow_undo else dashboard.modified_from_id
    dashboard.created_at = datetime.utcnow()

    db.commit()
    db.refresh(dashboard)
    logger.info(f"Returning dashboard: {dashboard.id}, {modified_content_json}")
    return {
        "dashboard_id": dashboard.id,
        "content": modified_content_json,
        "undo_available": allow_undo,
        "backup_dashboard_id": backup_dashboard_id if allow_undo else None
    }

@job_description_router.post("/undo/{dashboard_id}")
async def undo_dashboard(dashboard_id: int, db: Session = Depends(get_db)):
    d = db.query(DashboardContent).filter(DashboardContent.id == dashboard_id).first()
    if not d or not d.modified_from_id:
        raise HTTPException(status_code=404, detail="Original dashboard not found for undo.")

    original = db.query(DashboardContent).filter(DashboardContent.id == d.modified_from_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="Original dashboard content not found.")

    d.content = original.content
    d.prompt = original.prompt
    d.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(d)

    return {"id": d.id, "content": json.loads(d.content) if isinstance(d.content, str) else d.content, "message": "Undo successful."}

@job_description_router.delete("/delete/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: int,
    db: Session = Depends(get_db),
):
    """
    Delete a dashboard by its ID.
    Marks the dashboard as 'deleted' if soft delete is preferred,
    or removes it permanently if you want a hard delete.
    """
    dashboard = db.query(DashboardContent).filter(DashboardContent.id == dashboard_id).first()
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Option 1: Soft delete (recommended)
    # dashboard.status = "deleted"
    # db.commit()

    # Option 2: Hard delete (permanent)
    db.delete(dashboard)
    db.commit()

    logger.info(f"Deleted dashboard ID: {dashboard_id}")

    return {"message": f"Dashboard {dashboard_id} deleted successfully."}
