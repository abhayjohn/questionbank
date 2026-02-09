import streamlit as st
import pdfplumber
import json
import base64
import requests
import re
import os

# --- 1. ACCESS SECRETS ---
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"].strip()
    REPO_OWNER = st.secrets["REPO_OWNER"].strip()
    REPO_NAME = st.secrets["REPO_NAME"].strip()
    BRANCH = st.secrets.get("BRANCH", "main").strip()
except KeyError:
    st.error("Missing secrets! Please configure GITHUB_TOKEN, REPO_OWNER, and REPO_NAME in your secrets.")
    st.stop()

# --- 2. PDF PARSING LOGIC ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += page.extract_text() + "\n"

    # Split the text into blocks starting with Q.1, Q.2, etc.
    blocks = re.split(r'Q\.\d+', full_text)[1:]
    
    for idx, block in enumerate(blocks):
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        question_text = ""
        options = []
        answer = ""

        for line in lines:
            # Match options like "1. Option", "X 2. Option", or "✔ 3. Option"
            if re.match(r'^([X✔]?\s*[1-4]\.)', line):
                clean_opt = re.sub(r'^[X✔]?\s*[1-4]\.\s*', '', line)
                options.append(clean_opt)
                # Identify correct answer based on green tick or Ans marker
                if '✔' in line or 'Ans' in line:
                    answer = clean_opt
            elif not options and "Ans" not in line and "Source" not in line:
                question_text += line + " "

        if question_text and len(options) >= 2:
            all_questions.append({
                "id": idx + 1,
                "question": question_text.strip(),
                "options": options[:4],
                "answer": answer if answer else (options[0] if options else "")
            })
    return all_questions

# --- 3. GITHUB API LOGIC ---
def push_to_git(filename, content):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Check if file exists to get SHA (required for updates)
    res = requests.get(url, headers=headers)
    sha = res.json().get('sha') if res.status_code == 200 else None
    
    payload = {
        "message": f"Upload quiz: {filename}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha
        
    return requests.put(url, headers=headers, json=payload)

def fetch_quiz_list():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        return [f['name'] for f in res.json() if f['name'].endswith('.json')]
    return []

def fetch_quiz_content(filename):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        encoded_content = res.json()['content']
        return json.loads(base64.b64decode(encoded_content).decode())
    return None

# --- 4. STREAMLIT UI ---
def main():
    st.title("🚉 RRB JE Smart Quiz System")
    tab1, tab2 = st.tabs(["📤 Upload & Convert", "✍️ Take Quiz"])

    # TAB 1: CONVERTER
    with tab1:
        st.header("PDF to JSON Converter")
        uploaded_file = st.file_uploader("Upload your RRB PDF", type="pdf")
        
        if uploaded_file:
            if st.button("Extract and Sync to GitHub"):
                with st.spinner("Parsing PDF..."):
                    questions = parse_rrb_pdf(uploaded_file)
                    if not questions:
                        st.error("No questions found. Check PDF format.")
                    else:
                        quiz_data = {
                            "metadata": {
                                "exam_name": "RRB JE",
                                "test_date": "16/12/2024", # Customize parsing to extract this
                                "shift": "1"
                            },
                            "questions": questions
                        }
                        
                        json_content = json.dumps(quiz_data, indent=4)
                        # Clean filename
                        fname = f"RRB_JE_16Dec_S1_{len(questions)}Q.json"
                        
                        resp = push_to_git(fname, json_content)
                        if resp.status_code in [200, 201]:
                            st.success(f"Success! {len(questions)} questions pushed to GitHub.")
                        else:
                            st.error(f"Error {resp.status_code}: {resp.json().get('message')}")

    # TAB 2: QUIZ
    with tab2:
        st.header("Available Practice Papers")
        quiz_files = fetch_quiz_list()
        
        if not quiz_files:
            st.info("No quizzes found in the 'quizzes' folder on GitHub.")
        else:
            selected_quiz = st.selectbox("Choose a paper", quiz_files)
            if selected_quiz:
                quiz_data = fetch_quiz_content(selected_quiz)
                
                if quiz_data:
                    st.subheader(f"Paper: {quiz_data['metadata']['exam_name']} - {quiz_data['metadata']['test_date']}")
                    
                    user_answers = {}
                    for q in quiz_data["questions"]:
                        st.write(f"**Q{q['id']}:** {q['question']}")
                        user_answers[q['id']] = st.radio("Options:", q['options'], key=f"q_{q['id']}_{selected_quiz}", index=None)
                        st.write("---")

                    if st.button("Submit Quiz"):
                        score = 0
                        total = len(quiz_data["questions"])
                        for q in quiz_data["questions"]:
                            if user_answers[q['id']] == q['answer']:
                                score += 1
                        
                        # Apply RRB 1/3 negative marking logic
                        wrong = total - score
                        final_marks = score - (wrong * (1/3))
                        
                        st.balloons()
                        st.sidebar.metric("Score", f"{score}/{total}")
                        st.sidebar.metric("Net Marks", f"{final_marks:.2f}")
                        st.sidebar.caption("Negative Marking: 1/3 per wrong answer")

if __name__ == "__main__":
    main()
