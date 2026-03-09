from typing import Dict, List
import os
import time
import sounddevice as sd
import soundfile as sf
import numpy as np
import speech_recognition as sr
from app.core.Config import logger
from app.core.Config import GOOGLE_API_KEY
import google.generativeai as genai
import re

from fastapi import UploadFile

if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY is not set in environment variables")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

class PromptEngineering:
    UPLOAD_DIR = "uploads"
    SAMPLE_RATE = 44100
    audio_data = []
    recording_stream = None
    
    ALLOWED_EXTENSIONS = {
        ".pdf", ".docx", ".doc",
        ".json", ".csv", ".xlsx", ".xls",
        ".txt", ".rtf", ".md",
        ".xml", ".yaml", ".yml"
    }

  
    def generate_qa_prompt(section_content: str, num_questions: int) -> Dict[str, str]:
        try:
            prompt = f"""
            Based on this section content, generate {num_questions} interview questions and their ideal answers:
            {section_content}
            
            Format each Q&A pair exactly like this:
            Q1: [Question here]
            Expected Answer: [Answer here]
            """
            
            response = model.generate_content(prompt)
            return {
                "status": "success",
                "qa_content": response.text.strip()
            }
        except Exception as e:
            logger.error(f"Error generating QA: {str(e)}")
            return {
                "status": "error",
                "error": str(e)
            }

    def generate_follow_up_prompt(question: str, answer: str) -> str:
        return f"""
        Based on this Q&A:
        Q: {question}
        A: {answer}
        
        Generate 3 follow-up questions that:
        1. Probe technical depth
        2. Test practical application
        3. Verify understanding
        
        Format: Q1: [question]
        """

    def start_recording() -> Dict[str, str]:
        try:
            os.makedirs(PromptEngineering.UPLOAD_DIR, exist_ok=True)
            PromptEngineering.audio_data = []
            
            def callback(indata, frames, time, status):
                PromptEngineering.audio_data.append(indata.copy())
            
            PromptEngineering.recording_stream = sd.InputStream(
                channels=1,
                samplerate=PromptEngineering.SAMPLE_RATE,
                callback=callback
            )
            PromptEngineering.recording_stream.start()
            return {"status": "success", "message": "Recording started"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def stop_recording() -> Dict[str, str]:
        if PromptEngineering.recording_stream:
            try:
                PromptEngineering.recording_stream.stop()
                PromptEngineering.recording_stream.close()
                
                filename = f"recording_{int(time.time())}.wav"
                filepath = os.path.join(PromptEngineering.UPLOAD_DIR, filename)
                
                audio_data = np.concatenate(PromptEngineering.audio_data)
                sf.write(filepath, audio_data, PromptEngineering.SAMPLE_RATE)
                
                PromptEngineering.audio_data = []
                PromptEngineering.recording_stream = None
                
                return {
                    "status": "success",
                    "filename": filename,
                    "message": "Recording stopped successfully"
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to stop recording"
                }
        return {
            "status": "error",
            "error": "No active recording session",
            "message": "No recording to stop"
        }

    def transcribe_audio(filename: str) -> Dict[str, str]:
        try:
            audio_path = os.path.join(PromptEngineering.UPLOAD_DIR, filename)
            recognizer = sr.Recognizer()
            
            with sr.AudioFile(audio_path) as source:
                audio = recognizer.record(source)
                text = recognizer.recognize_google(audio)
                return {"status": "success", "text": text}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def evaluate_answer_prompt(question: str, answer: str) -> dict:
        prompt = f"""
        Evaluate this recorded answer against the expected answer format:
        
        Recorded Question: {question}
        Recorded Answer: {answer}
        
        Evaluate and provide scores in exactly this format:
        Technical: [score 0-100]
        Clarity: [score 0-100]
        Completeness: [score 0-100]
        Overall: [brief evaluation]
        """
        
        response = model.generate_content(prompt)
        evaluation_text = response.text.strip()
        
        evaluation_data = {
            "technical": int(re.search(r"Technical: (\d+)", evaluation_text).group(1)),
            "clarity": int(re.search(r"Clarity: (\d+)", evaluation_text).group(1)),
            "completeness": int(re.search(r"Completeness: (\d+)", evaluation_text).group(1)),
            "overall": re.search(r"Overall: (.+)$", evaluation_text, re.MULTILINE).group(1).strip()
        }
        
        return evaluation_data

class JobAnalysisPrompts:
    
    ANALYSIS_TEMPLATE = """
    Analyze the following job description carefully and extract structured information.

    Important parsing rules:
       - Each field in the job text (e.g., "Job Title:", "Location:", "Employment Type:") represents SEPARATE information.
        - The "Job Title" field must include ONLY the actual role title (e.g., "IT Support Specialist").
        - Do NOT include the location, employment type, or any other fields in the job title.
        - If any field is missing, infer it from context or write "Not specified".
        - Return the result in the exact format shown below. Do not include explanations, bullet points, or commentary.

        ### Extract the following fields:
        1. Job Title — the exact role title (e.g., "Software Engineer").
        2. Department/Industry — the department or domain (e.g., "Information Technology", "Finance").
        3. Required Skills — must-have skills, in comma-separated form.
        4. Experience Level — indicate the required experience as a level ("Entry", "Mid", "Senior") based on the number of years mentioned or the description in the job posting (e.g., "Entry" for 0–2 years, "Mid" for 2–5 years, "Senior" for 5+ years). If not specified, write "Not specified".
        5. Education Requirements — minimum education qualifications.
        6. Role Description — summarize the main responsibilities in 2–3 sentences.
        7. Employment Type — if mentioned (Full-time, Part-time, Contract, etc.).
        8. Keywords — extract important skills or concepts mentioned (comma-separated).
        9.Experience — years or level of experience (e.g., "3+ years")

        Return the result EXACTLY in the following format (no bullet points, no extra commentary):

        JOB_TITLE: [Extracted job title]
        DEPARTMENT: [Extracted department or industry]
        REQUIRED_SKILLS: [Skill 1, Skill 2, ...]
        EXPERIENCE: [Years or experience level, e.g., "3+ years", "Senior"]
        EXPERIENCE_LEVEL: [Entry, Mid, Senior]
        EDUCATION: [Education requirements]
        ROLE_DESCRIPTION: [Concise role summary]
        EMPLOYMENT_TYPE: [Employment type]
        KEYWORDS: [Keyword 1, Keyword 2, ...]

        ---

        Example 1:

        Job Description:
        We are looking for a Senior Python Developer in the Engineering department. The candidate should have 5+ years of experience, know Python, Django, and REST APIs. Bachelor’s degree in Computer Science is required. This is a full-time role.

        Output:
        JOB_TITLE: Senior Python Developer
        DEPARTMENT: Engineering
        REQUIRED_SKILLS: Python, Django, REST APIs
        EXPERIENCE: 5+ years
        EXPERIENCE_LEVEL: Senior
        EDUCATION: Bachelor’s degree in Computer Science
        ROLE_DESCRIPTION: We are looking for a Senior Python Developer in the Engineering department. The candidate should have 5+ years of experience, know Python, Django, and REST APIs.
        EMPLOYMENT_TYPE: Full-time
        KEYWORDS: Python, Django, REST APIs, Senior Developer

        ---

        Example 2:

        Job Description:
        Marketing Manager needed for our Sales department. Experience in digital marketing and social media management required. MBA preferred. Contract role.

        Output:
        JOB_TITLE: Marketing Manager
        DEPARTMENT: Sales
        REQUIRED_SKILLS: Digital marketing, Social media management
        EXPERIENCE: Not specified
        EXPERIENCE_LEVEL: Not specified
        EDUCATION: MBA preferred
        ROLE_DESCRIPTION: Marketing Manager needed for our Sales department. Experience in digital marketing and social media management required.
        EMPLOYMENT_TYPE: Contract
        KEYWORDS: Marketing, Digital marketing, Social media, Manager

        ---

        Now analyze this job description:


        Job Description:
        {context}
    """

    DASHBOARD_PROMPT_GENERATOR = """
        You are an expert prompt designer for generating short, focused dashboard prompts
        based on job descriptions (JDs).

        ### Purpose
        Generate {num_prompts} concise prompt ideas for dashboards that visualize or track
        key technical and soft skills listed in a JD.

        ### Focus
        - Each prompt should focus on **one or two skills/keywords only**, not all at once.
        - Each prompt should help visualize:
        - **Technical skills** (e.g., Python, SQL, MacOS, Windows, AI)
        - **Soft skills** (e.g., communication, teamwork, leadership, adaptability)
        - Assume no candidate data is available yet — these prompts are **conceptual templates**.

        ### Style Guidelines
        - Keep each prompt **short (1 sentence)** — under 20 words.
        - Start with action verbs: *Create*, *Design*, *Build*, *Generate*, *Summarize*, *Highlight*, etc.
        - Focus on **skills/keywords and outcomes**, not job description text.
        - Avoid redundant words like “based on the job description”.
        - Output should be a **JSON array of strings**, each being a standalone prompt.

        ### Example
        #### Input Keywords
        python, sql, data analysis, leadership, teamwork

        #### Output
        [
            "Create a dashboard highlighting Python proficiency levels.",
            "Design a dashboard showing teamwork impact.",
            "Generate insights tracking progress in data analysis.",
            "Build a dashboard comparing technical skill growth across projects.",
            "Summarize leadership effectiveness metrics."
        ]

        Now generate {num_prompts} concise dashboard prompts, each focusing on **one or two skills only**, 
        based on the following extracted skills:
        {keywords}
        """

    DASHBOARD_AUTOGEN_PROMPT = """
        You are an assistant that auto-generates insightful dashboards from Job Descriptions (JDs). Each dashboard provides a focused summary of key themes, technical areas, tools, or responsibilities found within the JD.

        The goal is to create **N dashboards** (where N is between 1 and 10), each centered on a unique skill/topic derived from the JD — such as “Python Expertise”, “Cloud Infrastructure”, “Data Engineering”, etc.

        ---

        ### JD Input:
        {jd_text}

        ---

        ### Output Instructions:

        - Extract 1 dashboard per topic (e.g., Python, DevOps, Data Analysis, etc.)
        - Generate exactly {count} distinct dashboards
        - Each dashboard must use the following JSON structure:

        ```json
        {{
            "dashboard_type": "auto",
            "dashboard_title": "<Topic or Skill Name>",
            "overview": [
            "<Bullet point 1>",
            "<Bullet point 2>",
            ...
            ]
        }}
        ```
        ---
        ###Output Rules:

        -Return a valid JSON list of dashboards (no markdown, no extra text)
        -Each JSON object in the list must follow the above format
        -dashboard_type is always "auto"
        -dashboard_title must be 2–4 words, concise and relevant to the JD
        -Each overview should have 5 to 7 bullet points
        -Bullet points must be:
            - Professional, concise, real-world applicable
            - Based on the JD (not generic)
            - Suitable for frontend widgets like cards, tabs, pie charts
            - Reflect skills, tools, responsibilities, or knowledge areas
            - Aim for 1 sentence or phrase per bullet
            - Keep it short, punchy, and focused on a single skill or responsibility
            - Around 10-15 words max helps keep dashboards readable and frontend-friendly
        ---

        ### Examples:

        #### Prompt: Python Expertise
        [
            {{
            "dashboard_type": "auto",
            "dashboard_title": "Python Expertise",
            "overview": [
                "Proficient in Python 3.x for scripting and automation",
                "Used Pandas, NumPy, and Matplotlib for data analysis",
                "Built ETL pipelines for structured and unstructured data",
                "Developed APIs with Flask and FastAPI",
                "Automated testing and deployment tasks",
                "Integrated with SQL and NoSQL databases"
            ]
            }},
            #### Prompt: Add CI/CD tasks
            {{
            "dashboard_type": "auto",
            "dashboard_title": "Cloud Infrastructure",
            "overview": [
                "Managed deployments on AWS EC2 and Lambda",
                "Used Terraform for infrastructure as code",
                "Configured CI/CD with Jenkins and GitHub Actions",
                "Secured environments with IAM and VPC setups",
                "Monitored cloud resources using CloudWatch and Grafana",
                "Automated backups and disaster recovery processes"
            ]
            }}
        ]
        IMPORTANT: DO NOT ADD ANY MARKDOWN OR CODE BLOCKS (NO ```json or ```), ONLY RETURN RAW JSON ARRAY WITHOUT ANY EXTRA TEXT.
        IMPORTANT: ONLY RETURN A SINGLE JSON ARRAY AND NOTHING ELSE. DO NOT RETURN MARKDOWN OR ANY EXPLANATION.

        }}"""

    CUSTOM_DASHBOARD_PROMPT = """
    You are an assistant that generates dashboards for Job Descriptions (JDs). Each dashboard should clearly show insights, metrics, or evaluation criteria derived from the JD or prompt. 
    You support two types of dashboards:

    1. Custom Dashboard: Generated from a custom prompt by the user (e.g., “Python Expertise” or “Cloud Skills”).
    2. Modified Dashboard: Generated by modifying an existing dashboard using a user-provided modification prompt (e.g., “Add CI/CD tasks”, “Replace AWS with Azure skills”).

    ---

    ### Output Format:

    Return a valid JSON object with the following structure:

    {
        "dashboard_type": "custom | modified",
        "dashboard_title": "<Skill or Topic Name>",
        "overview": [
        "<Bullet point 1>",
        "<Bullet point 2>",
        "<Bullet point 3>",
        ...
        ]
    }
    
    ---

    ### Output Rules:

    - Return only valid JSON — no markdown formatting, no code blocks, no extra text
    - The `dashboard_type` must be:
        - "custom" → if creating a new dashboard from a user prompt
        - "modified" → if modifying an existing dashboard using a modification instruction
    - `dashboard_title` should reflect the topic or skill area, based on the user prompt
    - The `overview` must contain 5 to 7 short, professional, actionable bullet points
    - Content must be frontend-friendly (used in pie charts, tabs, etc.)
    - Do not include `jd_id` or `sections` in this format
    Bullet points must be:
    -Each bullet should be one short sentence or phrase.
    -Around 10 to 15 words maximum per bullet.
    -  Keep it short, punchy, and focused on a single skill or responsibility
    -Avoid long, complex sentences or multiple ideas in one bullet.
    - Bullet points must reflect real-world skills, responsibilities, tools, or knowledge
    

    ---

    ### Examples:

    #### Prompt: Python Expertise

    {
        "dashboard_type": "custom",
        "dashboard_title": "Python Expertise",
        "overview": [
        "Proficient in Python 3.x for data analysis, automation, and web development",
        "Experience with libraries: Pandas, NumPy, Matplotlib, Scikit-learn",
        "Built ETL pipelines and data processing scripts for large datasets",
        "Developed REST APIs using Flask and FastAPI",
        "Automated reporting and data validation tasks",
        "Wrote unit and integration tests for Python codebases"
        ]
    }

    #### Prompt: Add CI/CD tasks

    {
        "dashboard_type": "custom", 
        "dashboard_title": "DevOps & CI/CD",
        "overview": [
            "Implemented CI/CD pipelines using Jenkins and GitHub Actions",
            "Automated build, test, and deployment processes",
            "Managed infrastructure as code with Terraform and Ansible",
            "Monitored application performance using Prometheus and Grafana",
            "Collaborated with development teams to streamline release cycles",
            "Ensured security compliance in deployment workflows"
        ]
    }

    #### Prompt: Technical Skills Summary
    {
    "dashboard_type": "custom",
    "dashboard_title":"Technical Skills Summary",
        "overview": [
            Languages: Python, SQL, DAX, JavaScript
            BI Tools: Power BI, Tableau, Looker
            Databases: BigQuery, SQL Server, PostgreSQL
            Cloud: Google Cloud Platform, Azure
            Version Control: Git, GitHub
            Other: REST APIs, ETL, Data Modeling
        ]
    }
    
    MODIFICATION INSTRUCTIONS (ONLY FOR modified type)
        When modification_prompt is given, you're updating an existing dashboard. You will be provided the following:
        •	Existing Dashboard Title
        •	Existing Overview Points
        •	Modification Prompt (e.g. "Add Terraform use", "Remove code review task")
        Your job is to:
        •	Apply the change requested by the prompt
        •	Retain the rest of the overview as-is
        •	Only change the title if the prompt says to
        •	Keep the dashboard focused and professional
        •   Retain the order and content of existing overview points, only add or remove points as explicitly requested in the modification prompt.
        •   If the modification prompt asks to "rephrase", "edit", or "change" a specific point, replace that point with the new, rephrased version while keeping the rest unchanged.
        •   If the modification prompt explicitly says "replace all overview points", "overwrite overview", or "update all points", then replace the entire overview list with the new provided points.
        • If the modification prompt says "change title", "rename dashboard", or "update dashboard title", update the dashboard_title accordingly.
        •   Append new points at the end unless the modification prompt specifies a different placement.

    #### Modification Prompt: Add Terraform scripting task
    Original Title: Scripting Proficiency (Bash, Python)
    Original Overview:
    •	Proficient in Bash scripting for automation
    •	Skilled in Python scripting for tooling
    •	Developed scripts for CI/CD and deployments
    •	Automated infrastructure tasks
    •	Wrote scripts for monitoring logs and health checks
    •	Created scripts for Docker/Kubernetes deployment
    Modification Prompt: Add a point related to using Terraform in scripts
    {
        "dashboard_type": "modified",
        "dashboard_title": "Scripting Proficiency (Bash, Python)",
        "overview": [
        "Proficient in Bash scripting for automation",
        "Skilled in Python scripting for tooling",
        "Developed scripts for CI/CD and deployments",
        "Automated infrastructure tasks",
        "Wrote scripts for monitoring logs and health checks",
        "Created scripts for Docker/Kubernetes deployment",
        "Used Terraform in Bash scripts to automate infrastructure provisioning"
        ]
    }

    """
    
#Job_description
# Improved prompt template for generating Q&A pairs from dashboard content

GENERATE_QA_PROMPT = """
Based on this dashboard content, generate {num_qa} relevant interview questions and their ideal answers.

INSTRUCTIONS:
1. Create concise, one-line questions.
2. Keep answers short — no more than 2–3 sentences.
3. Ensure each Q&A is clear, direct, and tightly tied to the dashboard content.
4. Use the selected difficulty level below to determine question complexity:
   - Beginner: Basic conceptual questions (Fresher-level).
   - Intermediate: Scenario-based or practical questions (Mid-level).
   - Advanced: Analytical or problem-solving questions (Senior-level).
5. Follow the format exactly as shown below.
6. Include variety in questioning style and focus on different aspects of the dashboard.
7. The dashboard content may come from either:
   - a Resume dashboard (candidate skills, projects, experience), or
   - a Job Description dashboard (role requirements, responsibilities, tools).
   Adapt questions accordingly.

FORMAT:
Q1: [One-line question]
A1: [Brief 2–3 sentence answer]
Q2: [One-line question]
A2: [Brief 2–3 sentence answer]
...

DIFFICULTY LEVEL: {difficulty}

DASHBOARD CONTENT:
{dashboard_content}

FEW-SHOT EXAMPLES:

=== Resume Dashboard ===

--- Beginner ---
Q1: What is the candidate’s primary technical skill shown in this dashboard?
A1: The dashboard highlights Python as the main skill. It also mentions FastAPI and MongoDB experience.

--- Intermediate ---
Q2: How would you evaluate the impact of the candidate’s ATS project?
A2: Review the system architecture, technologies used, and measurable outcomes delivered.

--- Advanced ---
Q3: How would you assess this candidate’s readiness for a GenAI engineering role?
A3: Focus on depth of LLM integration, scalability of services, and production monitoring practices.

=== Job Description Dashboard ===

--- Beginner ---
Q1: What is the main cloud platform required for this role?
A1: The dashboard specifies AWS along with Kubernetes for container orchestration.

--- Intermediate ---
Q2: How would you design a CI/CD pipeline based on these requirements?
A2: Use tools like GitHub Actions or Azure DevOps to build, test, and deploy containers into EKS.

--- Advanced ---
Q3: What risks could arise from poor Terraform state management in this role?
A3: It can cause infrastructure drift, deployment conflicts, or accidental resource deletion.

Generate exactly {num_qa} question–answer pairs following the format above.
"""


# Prompt template for generating similar Q&A pairs
GENERATE_SIMILAR_QA_PROMPT = """  
Based on this Q&A pair:
{original_qa}
Generate {num_pairs} different but similar Q&A pairs in the same format and topic.
Each Q&A should explore different aspects of the topic and use varied questioning approaches.
Ensure each pair is unique and covers different concepts within the same subject area.
Vary the complexity and specific details while maintaining relevance to the core topic.
Each pair should be separated by a blank line.
Format as:
Q: [Unique question about a different aspect]
A: [Detailed answer specific to that question]
"""

# Prompt template for evaluating answer accuracy
EVALUATE_QA_PROMPT = """Evaluate how well the following answer addresses the question. Consider:
1. Relevance to the question (aim for 95% relevance)
2. Completeness of the answer (aim for 100% completeness)
3. Accuracy of information (aim for 98% accuracy)
Question: {question}
Answer: {answer}
Provide a score from 0 to 100 and a brief explanation.
Return only two lines:
SCORE: [number]
EXPLANATION: [brief explanation]"""

# Prompt for AI-based question detection
QUESTION_STARTERS = """Analyze the following text and determine if it contains a question.
Consider all possible question formats, including:
1. Direct questions with question marks
2. Indirect questions without question marks
3. Implied questions or requests for information
4. Questions that don't start with traditional question words
5. Complex or compound questions
6. Follow-up probes or requests for elaboration
7 .Questions on trending keywords related to the JD and Resume Skills

Interview dialogue:
{dialogue}

Interviewer's last statement:
{statement}

Text to analyze:
{text}

Based on this interview dialogue, generate {num_questions} natural follow-up questions that the interviewer might ask next.
The questions should:
1. Flow naturally from the previous conversation
2. Probe deeper into topics already mentioned
3. Clarify any ambiguous or incomplete information
4. Theoritical questions that expect an answer in this context
5. Incomplete questions or interrupted speech
6. Assess the candidate's knowledge or experience in relevant areas
7. Vary between technical, behavioral, and situational questions as appropriate

Interview dialogue:
{dialogue}

Format your response as a numbered list of questions only.

From this interview statement, extract the core question or request for information.
Remove filler words, conversational elements, and reformat into a clear, direct question.
If multiple questions are present, extract the main question only.

Original statement:
{statement}

Return only the extracted question, nothing else.

Return only "YES" if the text contains a question, or "NO" if it doesn't.
"""
  