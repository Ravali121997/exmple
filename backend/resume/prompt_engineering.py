# Prompt constants for resume processing
Resume_GENERATE_QA_PROMPT = """
Based on the following resume dashboard content, generate exactly 10 relevant interview questions with answers.

Dashboard Content:
{dashboard_content}

Format each Q&A pair as:
Q: [Question]
A: [Answer]

Generate 10 pairs total.
"""

Resume_GENERATE_SIMILAR_QA_PROMPT = """
Based on the following original Q&A pair, generate {num_pairs} similar interview questions with answers.

Original Q&A:
{original_qa}

Format each Q&A pair as:
Q: [Question]
A: [Answer]

Generate {num_pairs} similar pairs.
"""

Resume_EVALUATE_QA_PROMPT = """
Evaluate the following interview answer for the given question.

Question: {question}
Answer: {answer}

Provide evaluation in this exact format:
SCORE: [percentage score 0-100%]
EXPLANATION: [Brief explanation of the evaluation]
"""

Resume_QUESTION_STARTERS = [
    "Tell me about",
    "Describe your experience with",
    "How would you",
    "What is your approach to",
    "Explain"
]

Resume_KEY_INFORMATION = [
    "skills",
    "experience",
    "projects",
    "education",
    "achievements"
]

# NEW: Prompt template for dashboard generation
Resume_DASHBOARD_PROMPT = """
CRITICAL INSTRUCTION: Generate {{num_dashboards}} resume analysis sections.

ABSOLUTELY FORBIDDEN (YOU WILL FAIL IF YOU USE ANY OF THESE):
DO NOT USE: * asterisks
DO NOT USE: # hash symbols  
DO NOT USE: - dashes at line start
DO NOT USE:  bullets
DO NOT USE: 1. 2. 3. numbered lists
DO NOT USE: **bold** markdown
DO NOT USE: ANY list format whatsoever

EXAMPLE OF FAILURE (NEVER DO THIS):
1. Phone number
2. College name 
- Current Role: Engineer
- Experience Level: Mid

YOU MUST USE ONLY:
Circle symbols      followed by complete descriptive sentences

CORRECT FORMAT EXAMPLE:
Career Development Analysis 
 Beginning the professional journey with foundational education at Aurora PG College and gaining initial exposure to technology concepts through academic projects.
 Transitioning into the role of AI ML Engineer with focus on machine learning implementations and contributing to software development projects.
 Developing expertise in technical problem solving and system optimization while working on collaborative team projects.
 Building proficiency in modern development practices and contributing to production level applications in technology sector.
 Advancing career through continuous learning and taking on increasing responsibilities in complex technical initiatives.

EXACT OUTPUT FORMAT:
SECTION_START
TITLE: [Section Name]
CONTENT:
[Topic Title]

 [Complete sentence describing first aspect with full details]
 [Complete sentence describing second aspect with full details]
 [Complete sentence describing third aspect with full details]
 [Complete sentence describing fourth aspect with full details]
 [Complete sentence describing fifth aspect with full details]
SECTION_END

Resume Content:
{text}

FINAL WARNING: If you generate "1. something" or "- something" you have COMPLETELY FAILED. Only      with full sentences.
"""




DASHBOARD_AUTOGEN_PROMPT = """
You are an assistant that auto-generates insightful dashboards from resumes.

Each dashboard provides a focused summary of key themes, technical areas, tools,
or responsibilities found within the resume.

The goal is to create **N dashboards** (where N is between 1 and 10), each centered on
a unique skill/topic derived from the resume — such as "Python Expertise",
"Cloud Infrastructure", "Data Engineering", etc.

---

### Resume Input:
{resume_text}

---

### Output Instructions:
- Extract 1 dashboard per topic (e.g., Python, DevOps, Data Analysis, etc.)
- Generate exactly {count} distinct dashboards
- Each dashboard must use the following JSON structure:

```json
{{
  "dashboard_type": "auto",
  "dashboard_title": "",
  "overview": [
    "",
    "",
    ...
  ]
}}
```

---

### Output Rules:
- Return a valid JSON list of dashboards (no markdown, no extra text)
- Each JSON object in the list must follow the above format
- dashboard_type is always "auto"
- dashboard_title must be 2–4 words, concise and relevant to the resume
- Each overview should have 5 to 7 bullet points
- Bullet points must be:
  - Professional, concise, real-world applicable
  - Based on the resume content (not generic)
  - Suitable for frontend widgets like cards, tabs, pie charts
  - Reflect skills, tools, responsibilities, or achievements from the candidate's career
  - Aim for 1 sentence or phrase per bullet
  - Keep it short, punchy, and focused on a single skill or responsibility
  - Around 10–15 words max per bullet to keep dashboards readable and frontend-friendly

---

### Examples:

#### Resume Topic: Python Expertise
[
  {{
    "dashboard_type": "auto",
    "dashboard_title": "Python Expertise",
    "overview": [
      "Proficient in Python 3.x for scripting, automation, and data analysis",
      "Used Pandas, NumPy, and Matplotlib across multiple projects",
      "Built ETL pipelines for structured and unstructured data",
      "Developed REST APIs using Flask and FastAPI",
      "Automated reporting and deployment workflows",
      "Integrated with SQL and NoSQL databases"
    ]
  }},

#### Resume Topic: Cloud Infrastructure
  {{
    "dashboard_type": "auto",
    "dashboard_title": "Cloud Infrastructure",
    "overview": [
      "Managed deployments on AWS EC2 and Lambda",
      "Used Terraform for infrastructure as code",
      "Configured CI/CD pipelines with Jenkins and GitHub Actions",
      "Secured environments using IAM and VPC configurations",
      "Monitored cloud resources with CloudWatch and Grafana",
      "Automated backup and disaster recovery processes"
    ]
  }}
]

IMPORTANT: DO NOT ADD ANY MARKDOWN OR CODE BLOCKS (NO ```json or ```), ONLY RETURN RAW JSON ARRAY WITHOUT ANY EXTRA TEXT.
IMPORTANT: ONLY RETURN A SINGLE JSON ARRAY AND NOTHING ELSE. DO NOT RETURN MARKDOWN OR ANY EXPLANATION.
}}"""

CUSTOM_DASHBOARD_PROMPT = """
You are an assistant that generates dashboards from resumes.

Each dashboard should clearly show insights, metrics, or evaluation criteria derived
from the resume or a user-provided prompt.

You support two types of dashboards:
1. **Custom Dashboard**: Generated from a custom prompt by the user
   (e.g., "Python Expertise" or "Cloud Skills").
2. **Modified Dashboard**: Generated by modifying an existing dashboard using a
   user-provided modification prompt
   (e.g., "Add CI/CD tasks", "Replace AWS with Azure skills").

---

### Output Format:
Return a valid JSON object with the following structure:

{{
  "dashboard_type": "custom | modified",
  "dashboard_title": "",
  "overview": [
    "",
    "",
    "",
    ...
  ]
}}

---

### Output Rules:
- Return only valid JSON — no markdown formatting, no code blocks, no extra text
- The `dashboard_type` must be:
  - "custom" → if creating a new dashboard from a user prompt
  - "modified" → if modifying an existing dashboard using a modification instruction
- `dashboard_title` should reflect the topic or skill area, based on the user prompt
- The `overview` must contain 5 to 7 short, professional, actionable bullet points
- Content must be frontend-friendly (used in pie charts, tabs, cards, etc.)
- Do not include `resume_id` or `sections` in this format

Bullet points must be:
- Each bullet should be one short sentence or phrase.
- Around 10 to 15 words maximum per bullet.
- Keep it short, punchy, and focused on a single skill or responsibility.
- Avoid long, complex sentences or multiple ideas in one bullet.
- Bullet points must reflect real-world skills, responsibilities, tools, or achievements
  found in the candidate's career history.

---

### Examples:

#### Prompt: Python Expertise
{{
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
}}

#### Prompt: Add CI/CD tasks
{{
  "dashboard_type": "custom",
  "dashboard_title": "DevOps & CI/CD",
  "overview": [
    "Implemented CI/CD pipelines using Jenkins and GitHub Actions",
    "Automated build, test, and deployment processes",
    "Managed infrastructure as code with Terraform and Ansible",
    "Monitored application performance using Prometheus and Grafana",
    "Collaborated with teams to streamline release cycles",
    "Ensured security compliance in deployment workflows"
  ]
}}

#### Prompt: Technical Skills Summary
{{
  "dashboard_type": "custom",
  "dashboard_title": "Technical Skills Summary",
  "overview": [
    "Languages: Python, SQL, DAX, JavaScript",
    "BI Tools: Power BI, Tableau, Looker",
    "Databases: BigQuery, SQL Server, PostgreSQL",
    "Cloud: Google Cloud Platform, Azure",
    "Version Control: Git, GitHub",
    "Other: REST APIs, ETL, Data Modeling"
  ]
}}

---

MODIFICATION INSTRUCTIONS (ONLY FOR modified type)

When modification_prompt is given, you're updating an existing dashboard.
You will be provided the following:
  • Existing Dashboard Title
  • Existing Overview Points
  • Modification Prompt (e.g. "Add Terraform use", "Remove code review task")

Your job is to:
  • Apply the change requested by the prompt
  • Retain the rest of the overview as-is
  • Only change the title if the prompt explicitly says to
  • Keep the dashboard focused and professional
  • Retain the order and content of existing overview points; only add or remove points
    as explicitly requested in the modification prompt.
  • If the modification prompt asks to "rephrase", "edit", or "change" a specific point,
    replace that point with the new version while keeping the rest unchanged.
  • If the modification prompt explicitly says "replace all overview points",
    "overwrite overview", or "update all points", replace the entire overview list.
  • If the modification prompt says "change title", "rename dashboard", or
    "update dashboard title", update the dashboard_title accordingly.
  • Append new points at the end unless the modification prompt specifies a different placement.

#### Modification Example:

Original Title: Scripting Proficiency (Bash, Python)
Original Overview:
  • Proficient in Bash scripting for automation
  • Skilled in Python scripting for tooling
  • Developed scripts for CI/CD and deployments
  • Automated infrastructure tasks
  • Wrote scripts for monitoring logs and health checks
  • Created scripts for Docker/Kubernetes deployment

Modification Prompt: Add a point related to using Terraform in scripts

{{
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
}}
"""

# NEW: Prompt for keyword extraction
Resume_KEYWORD_EXTRACTION_PROMPT = """
Extract the most important keywords from this resume text. 
Focus on:
1. Technical skills and tools
2. Programming languages and frameworks
3. Domain expertise and industry knowledge
4. Soft skills and competencies
5. Certifications and qualifications

Return only a list of keywords, separated by commas.

Resume text:
{text}
"""

Resume_sample_dashboard_prompts = """
You are an AI prompt designer specializing in resume analysis and data visualization.

Your task is to read the candidate’s resume and generate creative and diverse **dashboard generation prompts**.

Each prompt should help an AI system create dashboards that summarize or visualize key aspects of the candidate’s professional profile — such as skills, experience, education, and achievements.

Follow these rules:
1. Generate 5 to 7 distinct prompts.
2. Start each prompt with an action verb like "Create", "Generate", "Design", "Highlight", "Summarize", or "Outline".
3. Keep each prompt concise (one sentence only).
4. Focus on real resume themes — e.g., technical expertise, career growth, domain strengths, project outcomes, or performance metrics.
5. Use professional, natural language suitable for business dashboards.
6. If skills or experience are mentioned, tailor the prompts around them.
7. Return the output **as a JSON array** of strings.

Here is the candidate’s resume text:
---
{resume_text}
---

Example output:
[
  "Create a dashboard highlighting the candidate’s technical expertise and project achievements in Python and Data Analytics.",
  "Generate a visual summary of professional experience across roles, domains, and tools.",
  "Design an interactive dashboard summarizing educational qualifications and certifications.",
  "Highlight performance indicators and measurable results in project management tasks.",
  "Summarize leadership roles and teamwork contributions in past projects."
]
"""