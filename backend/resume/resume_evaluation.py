from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
# from app.services.resume.prompt_engineering import (Resume_GENERATE_QA_PROMPT,Resume_GENERATE_SIMILAR_QA_PROMPT,Resume_EVALUATE_QA_PROMPT,Resume_QUESTION_STARTERS,
# Resume_sample_dashboard_prompts,DASHBOARD_PROMPT_TEMPLATE)
from app.services.resume.llm_service import ResumeProcessorllm, Resume_DualInputTranscriber, PromptEngineering
from app.models.base import ResumeAnalytics, Candidate, JobDescription, ThresholdScore,Resume, DashboardContent
from app.services.gemini_model_loader import GeminiModelLoader 
from app.core import Config
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database.connection import get_db
import pdfplumber 

from datetime import datetime
# import speech_recognition as sr
import google.generativeai as genai
# import sounddevice as sd
import json
import logging
import os 
import tempfile
import uuid
from app.utils.file_validation import validate_resume_upload
from app.models.base_models import CustomPromptRequest
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

class InitializeRequest(BaseModel):
    api_key: str

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
    original_qa: str

resume_evaluation_router = APIRouter()

processor = ResumeProcessorllm()

class ResumeProcessor:
    def __init__(self):
        self.interviewer_lines = []
        self.candidate_lines = []
        self.status = "success"
        self.data = None
        self.error = None

    

    # Then initialize with the correct model name
    model = GeminiModelLoader.get_model()

def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text from a PDF file using pdfplumber.
    
    Args:
        file_path (str): Path to the PDF file.
        
    Returns:
        str: Extracted text from the PDF.
        
    Raises:
        Exception: If PDF processing fails.
    """
    try:
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        if not text.strip():
            logger.warning(f"No text extracted from PDF: {file_path}")
            return ""
        return text.strip()
    except Exception as e:
        logger.error(f"Failed to extract text from PDF {file_path}: {str(e)}")
        raise Exception(f"PDF text extraction failed: {str(e)}")

def format_resume_text(text):
    """
    Format resume text for better display
    
    Args:
        text: Raw resume text
        
    Returns:
        Formatted text with proper sections and spacing
    """
    import re
    
    # Replace bullet characters with proper markdown bullets
    text = text.replace('•', '\n- ')
    
    # Identify common section headers
    section_headers = [
        "EDUCATION", "EXPERIENCE", "SKILLS", "PROJECTS", "ACHIEVEMENTS", 
        "CERTIFICATIONS", "LANGUAGES", "INTERNSHIP", "PROFILE", "OBJECTIVE",
        "TECHNICAL SKILLS", "INTERPERSONAL SKILLS"
    ]
    
    # Add proper markdown formatting to section headers
    formatted_text = text
    for header in section_headers:
        # Match the header with word boundaries to avoid partial matches
        pattern = re.compile(r'\b' + re.escape(header) + r'\b', re.IGNORECASE)
        formatted_text = pattern.sub(f"\n\n {header}", formatted_text)
    
    # Clean up excessive newlines
    formatted_text = re.sub(r'\n{3,}', '\n\n', formatted_text)
    
    # Ensure proper spacing around section headers
    formatted_text = re.sub(r'( [^\n]+)', r'\n\1\n', formatted_text)
    
    # Format contact information at the top
    contact_info = []
    first_lines = formatted_text.split('\n\n')[0].split('\n')
    
    # Extract name (usually the first line)
    if first_lines and not first_lines[0].startswith(''):
        name = first_lines[0].strip()
        contact_info.append(f"# {name}")
    
    # Extract email, phone, location
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    phone_pattern = r'\b\d{10}\b|\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b'
    
    email_match = re.search(email_pattern, formatted_text)
    if email_match:
        contact_info.append(f"**Email:** {email_match.group(0)}")
    
    phone_match = re.search(phone_pattern, formatted_text)
    if phone_match:
        contact_info.append(f"**Phone:** {phone_match.group(0)}")
    
    # Look for address/location in the first few lines
    for line in first_lines[1:5]:  # Check the next few lines after name
        if "plot" in line.lower() or "street" in line.lower() or "road" in line.lower() or "nagar" in line.lower():
            contact_info.append(f"**Address:** {line.strip()}")
        elif any(city in line.lower() for city in ["hyderabad", "bangalore", "mumbai", "delhi", "chennai", "pune"]):
            contact_info.append(f"**Location:** {line.strip()}")
    
    # Add formatted contact info to the beginning
    if contact_info:
        contact_section = "\n".join(contact_info) + "\n\n---\n\n"
        # Remove the original contact info from the text to avoid duplication
        first_section_end = formatted_text.find('')
        if first_section_end > 0:
            formatted_text = contact_section + formatted_text[first_section_end:]
        else:
            formatted_text = contact_section + formatted_text
    
    return formatted_text


@resume_evaluation_router.post("/upload_Resume")
async def upload_resume(
    candidate_name: str = Form(None),
    candidate_email: str = Form(None),
    job_id: int = Form(None),
    candidate_id: int = Form(None),
    organization_id: int = Form(None),
    user_id: int = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        # Log all input parameters for debugging
        logger.debug(f"Input parameters: job_id={job_id}, candidate_id={candidate_id}, candidate_name={candidate_name}, candidate_email={candidate_email}, organization_id={organization_id}, user_id={user_id}, file={file.filename}")
        
        # Get dynamic threshold score from ThresholdScore table
        threshold_score = None
        
        if job_id is not None:
            # Try to get threshold score for this specific job
            job_threshold = db.query(ThresholdScore).filter(ThresholdScore.job_id == job_id).order_by(ThresholdScore.created_at.desc()).first()
            
            if job_threshold:
                threshold_score = job_threshold.threshold_value
                logger.info(f"Using job-specific threshold score for job_id {job_id}: {threshold_score}")
        
        # If no job-specific threshold found, try to get a general threshold
        if threshold_score is None:
            general_threshold = db.query(ThresholdScore).order_by(ThresholdScore.created_at.desc()).first()
            
            if general_threshold:
                threshold_score = general_threshold.threshold_value
                logger.info(f"Using general threshold score: {threshold_score}")
            else:
                # Default fallback value if no thresholds found in database
                threshold_score = 75.0  # Set a default value
                logger.info(f"No threshold scores found, using default: {threshold_score}")
        
        if job_id is not None:
            # Check if the job exists
            job_exists = db.query(JobDescription).filter(JobDescription.job_id == job_id).first()
            
            if not job_exists:
                logger.warning(f"Job ID {job_id} does not exist in database")
                # Try to get any existing job
                existing_job = db.query(JobDescription).first()
                if existing_job:
                    job_id = existing_job.job_id
                    logger.info(f"Using existing job_id: {job_id}")
                else:
                    # Create a default job with dynamic threshold
                    new_job = JobDescription(
                        title=f"Default Job Position",
                        description="This is a default job description created automatically.",
                        raw_text="Default job description",
                        status="Active",
                        threshold_score=threshold_score)
                    db.add(new_job)
                    db.flush()
                    job_id = new_job.job_id
                    logger.info(f"Created default job with ID: {job_id} and threshold: {threshold_score}")
        else:
            # If job_id is None, try to get any existing job
            existing_job = db.query(JobDescription).first()
            if existing_job:
                job_id = existing_job.job_id
                logger.info(f"Using existing job_id: {job_id}")
            else:
                # Create a default job with dynamic threshold
                new_job = JobDescription(
                    title=f"Default Job Position",
                    description="This is a default job description created automatically.",
                    raw_text="Default job description",
                    status="Active",
                    threshold_score=threshold_score
                )
                db.add(new_job)
                db.flush()
                job_id = new_job.job_id
                logger.info(f"Created default job with ID: {job_id} and threshold: {threshold_score}")
        
        # Make sure file is an UploadFile object with read method
        if not hasattr(file, 'read'):
            return JSONResponse(content={"status": "error", "error": "Invalid file object"}, status_code=400)
        
        # Read file content
        content = await file.read()
        await file.seek(0)
        
        # Create a temporary file to save the content
        temp_file_path = None
        try:
            # Create a temporary file with the correct extension
            file_extension = os.path.splitext(file.filename)[1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name
            
            # Extract text based on file type
            if file.filename.endswith('.pdf'):
                try:
                    # Use pdfplumber to extract text
                    text = extract_text_from_pdf(temp_file_path)
                except Exception as pdf_error:
                    logger.error(f"Error extracting PDF text: {str(pdf_error)}")
                    return JSONResponse(
                        content={"status": "error", "error": f"Error extracting PDF text: {str(pdf_error)}"}, 
                        status_code=400
                    )
            else:
                return JSONResponse(
                    content={"status": "error", "error": "Unsupported file type"}, 
                    status_code=400
                )
        finally:
            # Clean up the temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception as e:
                    logger.warning(f"Failed to delete temporary file {temp_file_path}: {str(e)}")
        
        # Extract keywords
        try:
            keywords = ResumeProcessorllm.extract_keywords(text)
        except Exception as kw_error:
            logger.error(f"Error extracting keywords: {str(kw_error)}")
            keywords = []
        
        # Improved name and email extraction
        try:
            extracted_info = ResumeProcessorllm.extract_candidate_info(text)
            logger.debug(f"Extracted info from resume: {extracted_info}")
        except Exception as info_error:
            logger.error(f"Error extracting candidate info: {str(info_error)}")
            extracted_info = {}
        
        # Use provided values or extracted values, with fallbacks
        candidate_name = candidate_name or extracted_info.get('name')
        if not candidate_name or candidate_name == "Unknown Candidate":
            # Try harder to extract a name from the resume
            try:
                candidate_name = ResumeProcessorllm.extract_name_advanced(text) or "Unknown Candidate"
                logger.debug(f"Advanced name extraction result: {candidate_name}")
            except Exception as name_error:
                logger.error(f"Error in advanced name extraction: {str(name_error)}")
                candidate_name = "Unknown Candidate"
        
        candidate_email = candidate_email or extracted_info.get('email')
        if not candidate_email:
            candidate_email = f"candidate_{int(datetime.now().timestamp())}@placeholder.com"
        
        # Check if candidate exists by ID or email
        candidate = None
        if candidate_id:
            candidate = db.query(Candidate).filter(Candidate.candidate_id == candidate_id).first()
            logger.debug(f"Found candidate by ID: {candidate}")
        
        # If not found by ID, check by email
        if not candidate and candidate_email:
            candidate = db.query(Candidate).filter(Candidate.email == candidate_email).first()
            logger.debug(f"Found candidate by email: {candidate}")
        
        if candidate:
            # Update existing candidate
            if candidate_name and candidate.name != candidate_name and candidate_name != "Unknown Candidate":
                candidate.name = candidate_name
            
            # IMPORTANT: Update job_id if provided and different
            if job_id is not None:
                # Double-check that the job exists before updating
                job_exists = db.query(JobDescription).filter(JobDescription.job_id == job_id).first()
                if job_exists:
                    candidate.job_id = job_id
                    logger.info(f"Updated candidate {candidate.candidate_id} with job_id: {job_id}")
                else:
                    logger.warning(f"Attempted to update candidate with non-existent job_id: {job_id}")
            
            # Update organization_id if provided
            if organization_id is not None:
                candidate.organization_id = organization_id
                logger.info(f"Updated candidate {candidate.candidate_id} with organization_id: {organization_id}")
            
            # Update resume_url
            candidate.resume_url = file.filename
            candidate.updated_at = datetime.now()
            
            db.flush()
            candidate_id = candidate.candidate_id
        else:
            # Create a new candidate
            try:
                # IMPORTANT: Ensure job_id is valid and exists
                job_exists = db.query(JobDescription).filter(JobDescription.job_id == job_id).first()
                if not job_exists:
                    logger.warning(f"Attempted to create candidate with non-existent job_id: {job_id}")
                
                # Create the candidate with a valid job_id
                candidate = Candidate(
                    name=candidate_name,
                    email=candidate_email,
                    job_id=job_id,
                    organization_id=organization_id,
                    status="Pending",
                    resume_url=file.filename
                )
                db.add(candidate)
                db.flush()  # Get the ID without committing
                candidate_id = candidate.candidate_id
                logger.info(f"Created new candidate {candidate_id} with job_id: {job_id}")
            except Exception as e:
                logger.error(f"Error creating candidate: {str(e)}")
                return JSONResponse(
                    content={"status": "error", "error": f"Error creating candidate: {str(e)}"}, 
                    status_code=400
                )
        
        # Check if resume already exists for this candidate
        existing_resume = None
        if candidate_id:
            existing_resume = db.query(Resume).filter(Resume.candidate_id == candidate_id).first()
            logger.debug(f"Found existing resume: {existing_resume}")
        
        if existing_resume:
            # Update existing resume
            existing_resume.resume_url = file.filename
            # IMPORTANT: Ensure job_id is updated in the resume
            if job_id is not None:
                existing_resume.job_id = job_id
            # Update organization_id and user_id if provided
            if organization_id is not None:
                existing_resume.organization_id = organization_id
            if user_id is not None:
                existing_resume.user_id = user_id
            existing_resume.is_active = True
            existing_resume.version += 1
            existing_resume.parsed_data = text
            existing_resume.upload_date = datetime.now()
            db.commit()  # Commit changes for existing resume
            resume_doc = existing_resume
            resume_id = existing_resume.resume_id  # Use existing resume_id
            logger.info(f"Updated existing resume {resume_doc.resume_id} with job_id: {job_id}, organization_id: {organization_id}, user_id: {user_id}")
        else:
            # Generate UUID string for resume_id (matches String column type)
            resume_id = str(uuid.uuid4())
            
            resume_doc = Resume(
                resume_id=resume_id,
                candidate_id=candidate_id,
                job_id=job_id,
                organization_id=organization_id,
                user_id=user_id,
                resume_url=file.filename,
                parsed_data=text,
                upload_date=datetime.now(),
                is_active=True,
                activity_type="upload"
            )
            db.add(resume_doc)
            db.commit()
            db.refresh(resume_doc)
            logger.info(f"Created new resume with resume_id: {resume_id}, job_id: {job_id}, organization_id: {organization_id}, user_id: {user_id}")
        
        # Store the extracted text in the global storage for use in other endpoints
        Config.RESUME_STORAGE["current_resume"] = {
            "resume_id": resume_id,
            "candidate_name": candidate_name or "Unknown Candidate",
            "text": text,
            "file_name": file.filename
        }
        
        # Verify the job_id was saved correctly
        db.refresh(resume_doc)
        db.refresh(candidate)
        logger.info(f"After commit - Resume job_id: {resume_doc.job_id}, Candidate job_id: {candidate.job_id}")
        
        return JSONResponse(
            content={
                "status": "success",
                "data": {
                    "keywords": keywords,
                    "text": text[:500] + "...",
                    "document_id": resume_doc.resume_id,
                    "candidate_id": candidate.candidate_id,
                    "candidate_name": candidate.name,
                    "candidate_email": candidate.email,
                    "job_id": resume_doc.job_id,
                    "threshold_score": threshold_score
                }
            },
            status_code=200
        )
    except Exception as e:
        # Rollback if needed
        try:
            if db and hasattr(db, 'rollback'):
                db.rollback()
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {str(rollback_error)}")
        
        # Log full traceback for debugging
        import traceback
        logger.error(f"Error in upload_Resume: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return JSONResponse(
            content={"status": "error", "error": f"Error processing file: {str(e)}"},
            status_code=500
        )
        
       

@resume_evaluation_router.post("/store-current-resume")
async def store_current_resume(
    text: str = Form(...),
    resume_id: Optional[str] = Form(None),
    candidate_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    db: Session = Depends(get_db)
) -> JSONResponse:
    try:
        # Clear the old cached resume data first
        if "current_resume" in Config.RESUME_STORAGE:
            del Config.RESUME_STORAGE["current_resume"]
            logger.info("Cleared old resume cache")
        
        # resume_id will be auto-generated by database if not provided
        
        # Format the resume text for better display
        formatted_text = format_resume_text(text)
        
        # FIRST CREATE DATABASE RECORD
        try:
            new_resume = None
            if resume_id:
                # Check if resume exists
                existing_resume = db.query(Resume).filter(Resume.resume_id == resume_id).first()
                if existing_resume:
                    existing_resume.parsed_data = formatted_text
                    existing_resume.activity_type = "store_current"
                    existing_resume.upload_date = datetime.utcnow()
                    new_resume = existing_resume
            
            if not new_resume:
                # Generate UUID string for resume_id (matches String column type)
                resume_id = str(uuid.uuid4())
                
                new_resume = Resume(
                    resume_id=resume_id,
                    resume_url="stored_resume",
                    parsed_data=formatted_text,
                    is_active=True,
                    version=1,
                    activity_type="store_current",
                    upload_date=datetime.utcnow()
                )
                db.add(new_resume)
                
            db.commit()
            db.refresh(new_resume)
            resume_id = new_resume.resume_id
            logger.info(f"Created database record for resume_id: {resume_id}")
            
            # Store the formatted resume data in the global RESUME_STORAGE
            Config.RESUME_STORAGE["current_resume"] = {
                "text": formatted_text,
                "raw_text": text,
                "resume_id": resume_id,
                "candidate_name": candidate_name,
                "email": email,
                "role": role,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as db_error:
            logger.warning(f"Could not create database record: {str(db_error)}")
            # Don't fail the request if DB creation fails
            resume_id = None
        
        logger.info(f"Stored resume in RESUME_STORAGE with ID: {resume_id}")
        
        return JSONResponse(
            content={
                "status": "success",
                "message": "Resume stored successfully",
                "resume_id": resume_id,
                "formatted": True
            },
            status_code=200
        )
    except Exception as e:
        logger.error(f"Error storing resume: {str(e)}")
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Failed to store resume: {str(e)}"
            },
            status_code=500
        )



@resume_evaluation_router.post("/clear-resume-cache")
async def clear_resume_cache() -> JSONResponse:
    """Clear the cached resume storage"""
    try:
        if "current_resume" in Config.RESUME_STORAGE:
            del Config.RESUME_STORAGE["current_resume"]
            logger.info("Resume cache cleared successfully")
            return JSONResponse(
                content={
                    "status": "success",
                    "message": "Resume cache cleared successfully"
                },
                status_code=200
            )
        else:
            return JSONResponse(
                content={
                    "status": "success",
                    "message": "No cache to clear"
                },
                status_code=200
            )
    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Failed to clear cache: {str(e)}"
            },
            status_code=500
        )


@resume_evaluation_router.get("/get-dashboard/{dashboard_id}")
async def get_dashboard(dashboard_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    result = await ResumeProcessorllm.get_dashboard_content(dashboard_id, db)
    return JSONResponse(
        content=result,
        status_code=200 if result["status"] == "success" else 404 if "not found" in result.get("message", "") else 500)

@resume_evaluation_router.get("/resume/{resume_id}")
async def get_resume_details(
    resume_id: str,
    user_id: int,
    organization_id: int = Query(None, description="Organization ID for access control"),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific resume by its resume_id
    """
    try:
        # Query the resume by resume_id with organization access control
        # Join with JobDescription to verify organization ownership
        if organization_id:
            # If organization_id is provided, filter by it
            resume = (
                db.query(Resume)
                .join(JobDescription, Resume.job_id == JobDescription.job_id)
                .filter(
                    Resume.resume_id == resume_id,
                    Resume.user_id == user_id,
                    JobDescription.organization_id == organization_id  # Ensure organization access
                )
                .first()
            )
        else:
            # If organization_id is not provided, just filter by resume_id and user_id
            resume = (
                db.query(Resume)
                .filter(
                    Resume.resume_id == resume_id,
                    Resume.user_id == user_id
                )
                .first()
            )
        
        if not resume:
            return JSONResponse(
                content={"status": "error", "message": f"Resume with ID {resume_id} not found or access denied"},
                status_code=404
            )
        
        # Get candidate information
        candidate = db.query(Candidate).filter(Candidate.candidate_id == resume.candidate_id).first()
        
        # Get job information if available
        job = None
        if resume.job_id:
            job = db.query(JobDescription).filter(JobDescription.job_id == resume.job_id).first()
        
        # Get analytics information - Cast resume_id to handle type mismatch
        analytics = db.query(ResumeAnalytics).filter(ResumeAnalytics.resume_id == str(resume_id)).all()
        
        # Format the response
        resume_data = {
            "resumeId": resume.resume_id,
            "candidateId": resume.candidate_id,
            "candidateName": candidate.name if candidate else "Unknown",
            "email": candidate.email if candidate else None,
            "phone": candidate.phone if candidate and hasattr(candidate, 'phone') else None,
            "role": job.title if job else "Unknown Role",
            "uploadDate": resume.upload_date.isoformat() if resume.upload_date else None,
            "status": resume.status if hasattr(resume, 'status') else "Pending",
            "version": resume.version,
            "isActive": resume.is_active,
            "content": resume.parsed_data,
            "resumeUrl": resume.resume_url,
            "analytics": [
                {
                    "id": analytic.analytics_id,
                    "type": analytic.activity_type,
                    "content": analytic.answer_text,
                    "status": analytic.status if hasattr(analytic, 'status') else None,
                    "createdAt": analytic.generated_at.isoformat() if analytic.generated_at else None
                } for analytic in analytics
            ],
            "jobDetails": {
                "jobId": job.job_id if job else None,
                "title": job.title if job else None,
                "description": job.description if job else None,
                "status": job.status if job and hasattr(job, 'status') else None,
                "thresholdScore": job.threshold_score if job and hasattr(job, 'threshold_score') else None
            } if job else None
        }
        
        return JSONResponse(
            content={"status": "success", "data": resume_data},
            status_code=200
        )
    except Exception as e:
        logger.error(f"Error retrieving resume details: {str(e)}")
        return JSONResponse(
            content={"status": "error", "message": f"Error retrieving resume details: {str(e)}"},
            status_code=500
        )
@resume_evaluation_router.post("/generate-qa")
async def generate_qa(
    dashboard_content: str = Form(...),
    num_qa: int = Form(default=5),
    db: Session = Depends(get_db)
) -> JSONResponse:
    try:
        # Generate UUID string for resume_id (matches String column type)
        resume_id = str(uuid.uuid4())
        
        resume = Resume(
            resume_id=resume_id,
            resume_url="qa_generation",
            parsed_data=dashboard_content,
            is_active=True,
            version=1
        )
        db.add(resume)
        db.commit()
        db.refresh(resume)

        qa_response = ResumeProcessorllm.generate_qa(dashboard_content, num_qa)
        
        # Extract the formatted_qa string from the response dictionary
        qa_content = qa_response["formatted_qa"] if isinstance(qa_response, dict) else str(qa_response)

        # Generate integer analytics_id manually
        max_analytics_id = db.query(func.max(ResumeAnalytics.analytics_id)).scalar() or 0
        analytics_id = max_analytics_id + 1
        
        qa_record = ResumeAnalytics(
            analytics_id=analytics_id,
            resume_id=resume.resume_id,
            ai_generated_question=f"Generated {num_qa} Q&A pairs",
            answer_text=qa_content,
            score=0.0,
            insights=json.dumps({
                "num_qa": num_qa, 
                "dashboard_content_length": len(dashboard_content),
                "qa_id": qa_response.get("qa_id"),
                "metadata": qa_response.get("metadata")
            }),
            activity_type="qa_generation",
            generated_at=datetime.utcnow()
        )

        db.add(qa_record)
        db.commit()
        db.refresh(qa_record)

        return JSONResponse(
            content={
                "status": "success",
                "data": {
                    "content": qa_content,
                    "qa_id": qa_record.analytics_id,
                    "resume_id": resume.resume_id,
                    "mongo_qa_id": qa_response.get("qa_id")
                }
            }
        )

    except Exception as e:
        if "db" in locals():
            db.rollback()
        return JSONResponse(
            content={"status": "error", "error": str(e)},
            status_code=500
        )


@resume_evaluation_router.get("/get-qa/{qa_id}")
async def get_qa(qa_id: str) -> JSONResponse:
    result = ResumeProcessorllm.get_qa_content(qa_id)
    return JSONResponse(content=result, status_code=200 if result["status"] == "success" else 404 if "not found" in result.get("message", "") else 500)

@resume_evaluation_router.post("/initialize")
async def initialize_transcriber(request: InitializeRequest) -> JSONResponse:
    try:
        if not request.api_key:
            raise HTTPException(status_code=400, detail="API key is required")
        response = await Resume_DualInputTranscriber.initialize(request.api_key)
        return JSONResponse(
            content=response,
            status_code=200 if response["status"] == "success" else 400,
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "error": str(e)}, status_code=500
        )

@resume_evaluation_router.post("/start-recording")
async def start_recording(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        response = await Resume_DualInputTranscriber.start_recording(
            Resume_DualInputTranscriber, db
        )
        logger.info(f"Start recording response: {response}")
        return JSONResponse(
            content=response,
            status_code=200 if response["status"] == "success" else 400,
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "error": str(e)}, status_code=500
        )

@resume_evaluation_router.post("/stop-recording")
async def stop_recording(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        # Pass DualInputTranscriber as the first argument explicitly
        response = await Resume_DualInputTranscriber.stop_recording(
            Resume_DualInputTranscriber, db
        )
        return JSONResponse(
            content=response,
            status_code=200 if response["status"] == "success" else 400,
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "error": str(e)}, status_code=500
        )

@resume_evaluation_router.post("/clear-transcription")
async def clear_transcription() -> JSONResponse:
    try:
        response = await Resume_DualInputTranscriber.clear_transcription()
        return JSONResponse(
            content=response,
            status_code=200 if response["status"] == "success" else 400,
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "error": str(e)}, status_code=500
        )

@resume_evaluation_router.post("/evaluate-qa")
async def evaluate_qa() -> JSONResponse:
    try:
        response = await Resume_DualInputTranscriber.evaluate_qa(Resume_DualInputTranscriber)
        return JSONResponse(
            content={
                "status": "success",
                "data": {
                    "explanation": response.get("explanation", "Invalid Q&A format"),
                    "mark": response.get("mark", "[ERROR]"),
                    "score": response.get("score", "0%"),
                    "eval_id": response.get("eval_id", ""),
                },
            }
        )
    except Exception as e:
        return JSONResponse(
            content={
                "status": "success",
                "data": {
                    "explanation": "Invalid Q&A format",
                    "mark": "[ERROR]",
                    "score": "0%",
                },
            }
        )

@resume_evaluation_router.get("/get-evaluation/{eval_id}")
async def get_evaluation(eval_id: str) -> JSONResponse:
    try:
        # For testing purposes, return a mock response for any ID
        if eval_id == "mock_eval_123":
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {
                        "explanation": "The candidate provided a comprehensive answer that covered all key points. They demonstrated strong technical knowledge and clear communication.",
                        "mark": "[SUCCESS]",
                        "score": "85%",
                        "eval_id": "mock_eval_123"
                    }
                }
            )
        elif eval_id == "mock_error_eval":
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {
                        "explanation": "Invalid Q&A format",
                        "mark": "[ERROR]",
                        "score": "0%",
                        "eval_id": "mock_error_eval"
                    }
                }
            )
        else:
            # Try to use the Resume_DualInputTranscriber function
            try:
                result = Resume_DualInputTranscriber.get_evaluation_qa_content(eval_id)
                return JSONResponse(content=result)
            except Exception as func_error:
                logger.error(f"Error in get_evaluation_qa_content: {str(func_error)}")
                return JSONResponse(
                    content={
                        "status": "error",
                        "message": f"No evaluation found with ID: {eval_id}"
                    },
                    status_code=404
                )
    except Exception as e:
        logger.error(f"Error in get_evaluation: {str(e)}")
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Error retrieving evaluation content: {str(e)}"
            },
            status_code=500
        )

@resume_evaluation_router.post("/generate_QA_from_audio")
async def generate_qa_from_audio(request: GenerateQARequest):
    try:
        original_qa, result = Resume_DualInputTranscriber.generate_similar_qa(request.num_pairs, request.original_qa)
        if isinstance(result, dict):
            return JSONResponse(
                content={
                    "status": "success",
                    "data": {
                        "original": original_qa,
                        "generated": result["generated_text"],
                        "qa_id": result["qa_id"],
                        "metadata": result["metadata"]}}, status_code=200)
        else:
            # Handle error case where result is error message string
            return JSONResponse(content={
                    "status": "success",
                    "data": {"original": original_qa, "generated": result}}, status_code=200)
            
    except Exception as e:
        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)

@resume_evaluation_router.get("/get-audio-qa/{qa_id}")
async def get_audio_qa(qa_id: str) -> JSONResponse:
    try:
        result = ResumeProcessorllm.get_audio_qa_content(qa_id)
        return JSONResponse(
            content=result,
            status_code=200 if result["status"] == "success" else 404 if "not found" in result.get("message", "") else 500
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "error": str(e)},
            status_code=500
        ) 
   


@resume_evaluation_router.post("/dashboard_custom_prompt/{resume_id}")
async def run_custom_prompt_resume(
    resume_id: str,
    request: CustomPromptRequest,
    db: Session = Depends(get_db)
):
    prompt = request.prompt

    resume = db.query(Resume).filter(Resume.resume_id == resume_id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    try:
        processor = ResumeProcessorllm()
        content = processor.generate_dashboard(
            resume_id=resume.resume_id,          # reuse same param
            resume_text=resume.parsed_data,      # resume text
            dashboard_type="custom",
            custom_prompt=prompt
        )
    except Exception as e:
        logger.error(f"LLM Error in /custom_prompt/{resume_id}: {e}")
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
        job_id=None,
        resume_id=resume.resume_id,
        prompt=prompt,
        text=resume.parsed_data,
        content=json.dumps(content_json),
        dashboard_type="custom",
        created_at=datetime.utcnow(),
        status="active"
    )

    db.add(dashboard)
    db.commit()
    db.refresh(dashboard)

    return {
        "data": {
            "dashboard_id": dashboard.id,
            "content": content_json
        }
    }


@resume_evaluation_router.post("/generate/{resume_id}")
async def auto_generate_dashboards_resume(
    resume_id: str,
    count: int = Query(1, ge=1, le=10),
    db: Session = Depends(get_db)
) -> dict:

    # Fetch resume
    resume = db.query(Resume).filter(Resume.resume_id == resume_id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Step 1: Get existing dashboards
    existing_dashboards = (
        db.query(DashboardContent)
        .filter(
            DashboardContent.resume_id == resume_id,
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
            "resume_id": resume_id,
            "count": count,
            "dashboards": [
                {
                    "dashboard_id": d.id,
                    "dashboard_title":ResumeProcessorllm.parse_content(d.content).get("dashboard_title"),
                    "overview": ResumeProcessorllm.parse_content(d.content).get("overview")
                }
                for d in existing_dashboards[:count]
            ]
        }

    # Step 3: Generate missing dashboards
    missing_count = count - existing_count
    logger.info(f"Generating {missing_count} new dashboards for resume {resume_id}")

    processor = ResumeProcessorllm()
    new_dashboards = processor.generate_multiple_dashboards_from_resume(
        resume_text=resume.parsed_data,  # reuse same function
        count=missing_count
    )

    if not isinstance(new_dashboards, list) or not all(isinstance(d, dict) for d in new_dashboards):
        raise HTTPException(status_code=500, detail="Invalid dashboard format returned.")

    dashboards_to_add = []

    for dashboard_data in new_dashboards:
        dashboard = DashboardContent(
            job_id=None,
            resume_id=resume.resume_id,
            prompt="",
            text=resume.parsed_data,  
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
        logger.error(f"DB transaction failed for resume dashboards: {e}")
        raise HTTPException(status_code=500, detail="Database error during dashboard creation.")

    return {
        "resume_id": resume_id,
        "count": len(existing_dashboards),
        "dashboards": [
            {
                "dashboard_id": d.id,
                "dashboard_title": ResumeProcessorllm.parse_content(d.content).get("dashboard_title"),
                "overview": ResumeProcessorllm.parse_content(d.content).get("overview")
            }
            for d in existing_dashboards[:count]
        ]
    }


@resume_evaluation_router.post("/dashboard_modify/{dashboard_id}")
async def modify_existing_dashboard_resume(
    dashboard_id: int,
    modification_prompt: str = Query(..., description="Prompt describing changes to the dashboard"),
    allow_undo: bool = Query(True, description="Whether to keep a backup of the original dashboard for undo"),
    db: Session = Depends(get_db),
):
    """
    Modify an existing resume dashboard using a prompt.
    Updates the current dashboard in place, with optional backup for undo.
    """

    dashboard = db.query(DashboardContent).filter(DashboardContent.id == dashboard_id).first()
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Ensure this dashboard belongs to a resume
    if not dashboard.resume_id:
        raise HTTPException(status_code=400, detail="This dashboard is not linked to a resume.")

    # Backup original dashboard (if undo allowed)
    backup_dashboard_id = None
    if allow_undo:
        backup_dashboard = DashboardContent(
            job_id=None,
            resume_id=dashboard.resume_id,
            prompt=dashboard.prompt,
            text=dashboard.text,
            content=dashboard.content,
            dashboard_type=dashboard.dashboard_type,
            modified_from_id=dashboard.modified_from_id,
            created_at=dashboard.created_at,
            status="backup",
        )
        db.add(backup_dashboard)
        db.flush()
        backup_dashboard_id = backup_dashboard.id

    # Call LLM to modify content
    try:
        processor = ResumeProcessorllm()

        modified_content = processor.generate_dashboard(
            resume_id=dashboard.resume_id,     # resume_id is str
            resume_text=dashboard.text,        # resume text
            dashboard_type="modified",
            custom_prompt=modification_prompt,
            base_dashboard_content=dashboard.content,
        )

    except Exception as e:
        logger.error(f"LLM Error in /modify/{dashboard_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to modify dashboard. Please try again.")

    # Parse result safely
    if isinstance(modified_content, str):
        try:
            modified_content_json = json.loads(modified_content)
        except json.JSONDecodeError:
            modified_content_json = modified_content
    else:
        modified_content_json = modified_content

    # Update dashboard in place
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

    return {
        "dashboard_id": dashboard.id,
        "content": modified_content_json,
        "undo_available": allow_undo,
        "backup_dashboard_id": backup_dashboard_id if allow_undo else None
    }


@resume_evaluation_router.post("/sample_prompts/{resume_id}")
async def get_sample_prompts(resume_id: str, db: Session = Depends(get_db)):
    # Query using resume_id (string/UUID)
    resume = db.query(Resume).filter(Resume.resume_id == resume_id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Extract sections from parsed text
    sections = ResumeProcessorllm.extract_resume_sections(resume.parsed_data or "")
    
    # Generate sample prompts
    prompts = PromptEngineering.generate_sample_prompts(sections, num_prompts=5)
    
    return {"sample_prompts": prompts}

