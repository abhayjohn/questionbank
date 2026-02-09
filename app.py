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
except Exception:
    st.error("Missing Secrets! Configure GITHUB_TOKEN, REPO_OWNER, and REPO_NAME.")
    st.stop()

# --- 2. CONTEXT-AWARE PARSING LOGIC ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    noise_keywords = [
        "Adda247", "Adda 247", "Google Play", "INDIAN RAILWAYS", 
        "RAILWAY", "Subject", "Test Date", "Test Time", "Test Prime",
        "Chosen Option", "Status", "Question ID", "Source"
    ]
    
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    # Split by Q.Number pattern
    blocks = re.split(r'Q\.(\d+)', full_text)
    
    for i in range(1, len(blocks), 2):
        q_id = blocks[i]
        content = blocks[i+1]
        
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        question_parts = []
        options = []
        answer = ""

        for line in lines:
            # Match options 1-4 with greedy text capture
            opt_match = re.match(r'^([X✔]?\s*([1-4])\.)\s*(.*)', line)
            
            if opt_match:
                opt_text = opt_match.group(3).strip()
                if len(options) < 4:
                    options.append(opt_text)
                    if '✔' in line or 'Ans' in line:
                        answer = opt_text
            elif len(options) < 4:
                # Still looking for options; skip metadata and add to question
                if not any(key in line for key in noise_keywords) and "Ans" not in line:
                    question_parts.append(line)

        # Pad missing options to prevent app crashes
        while len(options) < 4:
            options.append("Option missing from PDF")

        all_questions.append({
            "id": int(q_id),
            "question": " ".join(question_parts).strip(),
            "options": options[:4],
            "answer": answer if answer else options[0]
        })
    
    all_questions.sort(key=lambda x: x['id'])
    return all_questions

# --- 3. GITHUB API HELPERS ---
def get_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

def push_to_git(filename, content):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    res = requests.get(url, headers=get_headers())
    sha = res.json().get('sha') if res.status_code == 200 else None
    
    payload = {
        "message": f"Sync {filename}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": BRANCH
    }
    if sha: payload["sha"] = sha
    return requests.put(url, headers=get_headers(), json=payload)

def delete_from_git(filename):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    res = requests.get(url, headers=get_headers())
    if res.status_code == 200:
        sha = res.json().get('sha')
        payload = {"message": f"Delete {filename}", "sha": sha, "branch": BRANCH}
        return requests.delete(url, headers=get_headers(), json=payload)
    return res

def fetch_files():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes"
    res = requests.get(url, headers=get_headers())
    if res.status_code == 200:
        return [f['name'] for f in res.json() if f['name'].endswith('.json')]
    return []

# --- 4. MAIN INTERFACE ---
def main():
    st.set_page_config(page_title="RRB JE Admin", layout="wide")
    
    # Sidebar Management
    st.sidebar.title("🛠️ Repo Management")
    existing_files = fetch_files()
    if existing_files:
        file_to_del = st.sidebar.selectbox("Delete a paper", existing_files)
        if st.sidebar.button("🗑️ Delete Selected"):
            if delete_from_git(file_to_del).status_code == 200:
                st.sidebar.success("Deleted!")
                st.rerun()
        if st.sidebar.button("🔥 WIPE ALL QUIZZES"):
            for f in existing_files: delete_from_git(f)
            st.sidebar.warning("Repository Cleared!")
            st.rerun()

    t1, t2 = st.tabs(["📤 Bulk Upload & Fix", "✍️ Practice Mode"])

    # TAB 1: UPLOADER
    with t1:
        st.header("Upload Multiple PDFs")
        files = st.file_uploader("Select RRB Exam PDFs", type="pdf", accept_multiple_files=True)
        
        if files:
            # Preview first file for debugging (Checks Q.4 specifically)
            st.subheader(f"Preview: {files[0].name}")
            preview_data = parse_rrb_pdf(files[0])
            st.write(f"Total Questions Detected: **{len(preview_data)}**")
            
            # Show specific question to verify fix
            q_idx = st.number_input("Preview Question #", min_value=1, max_value=len(preview_data), value=4)
            st.json(preview_data[q_idx-1])

            if st.button("🚀 Process & Push All to Git"):
                p_bar = st.progress(0)
                for i, f in enumerate(files):
                    qs = parse_rrb_pdf(f)
                    fname = re.sub(r'\.pdf$', '', f.name).replace(" ", "_") + ".json"
                    quiz_payload = {"metadata": {"file": f.name, "count": len(qs)}, "questions": qs}
                    push_to_git(fname, json.dumps(quiz_payload, indent=4))
                    p_bar.progress((i + 1) / len(files))
                st.success("All files synced to GitHub!")

    # TAB 2: QUIZ
    with t2:
        if existing_files:
            selected = st.selectbox("Choose Practice Paper", existing_files)
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{selected}"
            res = requests.get(url, headers=get_headers())
            quiz = json.loads(base64.b64decode(res.json()['content']).decode())
            
            st.header(f"📖 {selected}")
            user_answers = {}
            for q in quiz["questions"]:
                st.write(f"**Q{q['id']}:** {q['question']}")
                user_answers[q['id']] = st.radio("Choose:", q['options'], key=f"{selected}_{q['id']}", index=None)
                st.divider()
            
            if st.button("Finish & Grade"):
                correct = sum(1 for q in quiz["questions"] if user_answers[q['id']] == q['answer'])
                st.sidebar.metric("Score", f"{correct}/{len(quiz['questions'])}")
        else:
            st.info("Upload some papers in Tab 1 to start practicing.")

if __name__ == "__main__":
    main()
