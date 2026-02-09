import streamlit as st
import pdfplumber
import json
import base64
import requests
import re
import os

# --- GITHUB CONFIGURATION ---
# Store these in .streamlit/secrets.toml for security
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "your_token_here")
REPO_OWNER = "your_username"
REPO_NAME = "your_quiz_repo"
BRANCH = "main"

def parse_rrb_pdf(uploaded_file):
    """Extracts 100 questions from the uploaded PDF stream."""
    all_questions = []
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += page.extract_text() + "\n"

    # Split by Question markers (Q.1, Q.2, etc.)
    blocks = re.split(r'Q\.\d+', full_text)[1:]
    
    for idx, block in enumerate(blocks):
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        question_text = ""
        options = []
        answer = ""

        # Parsing logic tailored to the provided PDF structure
        for line in lines:
            # Detect options (e.g., 1. Option, X 2. Option, ✔3. Option)
            if re.match(r'^([X✔]?\s*[1-4]\.)', line):
                clean_opt = re.sub(r'^[X✔]?\s*[1-4]\.\s*', '', line)
                options.append(clean_opt)
                if '✔' in line or 'Ans' in line: # Marking the correct one
                    answer = clean_opt
            elif not options and "Ans" not in line:
                question_text += line + " "

        if question_text and len(options) >= 2:
            all_questions.append({
                "id": idx + 1,
                "question": question_text.strip(),
                "options": options[:4],
                "answer": answer if answer else options[0] # Fallback
            })
    return all_questions

def push_to_git(filename, content):
    """Pushes the JSON file to GitHub quizzes/ folder."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    # Get SHA if file exists to update it
    res = requests.get(url, headers=headers)
    sha = res.json().get('sha') if res.status_code == 200 else None
    
    payload = {
        "message": f"Add {filename}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": BRANCH
    }
    if sha: payload["sha"] = sha
    
    return requests.put(url, headers=headers, json=payload)

def main():
    st.set_page_config(page_title="RRB AI Portal", layout="wide")
    t1, t2 = st.tabs(["🚀 Converter", "📝 Practice Quiz"])

    # --- TAB 1: PDF CONVERSION ---
    with t1:
        st.header("Upload New Exam Paper")
        pdf_file = st.file_uploader("Drop RRB PDF here", type="pdf")
        
        if pdf_file:
            # Extracting metadata from your PDF header [cite: 5]
            exam_date = "16/12/2024" # In a full app, parse this from text
            shift = "1"
            
            if st.button("Convert & Sync to Git"):
                with st.spinner("Processing 100 questions..."):
                    questions = parse_rrb_pdf(pdf_file)
                    quiz_data = {
                        "metadata": {"exam_name": "RRB JE", "test_date": exam_date, "shift": shift},
                        "questions": questions
                    }
                    
                    json_str = json.dumps(quiz_data, indent=4)
                    file_name = f"RRB_JE_{exam_date.replace('/','_')}_S{shift}.json"
                    
                    response = push_to_git(file_name, json_str)
                    if response.status_code in [200, 201]:
                        st.success(f"Successfully uploaded {len(questions)} questions!")
                    else:
                        st.error(f"Git Error: {response.text}")

    # --- TAB 2: QUIZ RENDERING ---
    with t2:
        st.header("Exam Selection")
        # Ensure 'quizzes' folder exists locally for the app to read
        if not os.path.exists("quizzes"): os.makedirs("quizzes")
        
        files = [f for f in os.listdir("quizzes") if f.endswith(".json")]
        if files:
            selected = st.selectbox("Choose a Paper", files)
            with open(os.path.join("quizzes", selected), "r") as f:
                data = json.load(f)
            
            st.info(f"Loaded: {data['metadata']['exam_name']} ({data['metadata']['test_date']})")
            
            score = 0
            for q in data["questions"]:
                st.write(f"**Q{q['id']}**: {q['question']}")
                choice = st.radio("Options", q['options'], key=f"q_{q['id']}_{selected}", index=None)
                st.divider()
                # Scoring logic happens on a final submit button usually
        else:
            st.warning("No papers found in local 'quizzes' folder. Sync from Git or upload one!")

if __name__ == "__main__":
    main()
