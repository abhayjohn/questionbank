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
    st.error("Missing Secrets! Configure GITHUB_TOKEN, REPO_OWNER, and REPO_NAME in Secrets.")
    st.stop()

# --- 2. SUPER-GREEDY PARSING LOGIC (Fixes Q.4) ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += page.extract_text() + "\n"

    # Eliminate noise that sits between options and causes "Option Missing" errors
    noise = ["Adda247", "Adda 247", "Google Play", "INDIAN RAILWAYS", "RAILWAY", "Test Prime", "Source"]
    for word in noise:
        full_text = full_text.replace(word, "")

    q_pattern = re.compile(r'Q\.(\d+)')
    opt_pattern = re.compile(r'^([X✔]?\s*([1-4])\.)\s*(.*)')

    current_q = None
    
    for line in full_text.split('\n'):
        line = line.strip()
        if not line: continue

        q_match = q_pattern.match(line)
        if q_match:
            # Save the finished question before starting a new one
            if current_q and current_q['question']:
                while len(current_q['options']) < 4:
                    current_q['options'].append("Option missing from PDF")
                all_questions.append(current_q)
            
            current_q = {
                "id": int(q_match.group(1)),
                "question": line.replace(q_match.group(0), "").strip(),
                "options": [],
                "answer": ""
            }
            continue

        if current_q:
            opt_match = opt_pattern.match(line)
            if opt_match:
                opt_text = opt_match.group(3).strip()
                if len(current_q['options']) < 4:
                    current_q['options'].append(opt_text)
                    if '✔' in line or 'Ans' in line:
                        current_q['answer'] = opt_text
            else:
                # Still building the question text until we find 4 options
                if len(current_q['options']) < 4 and "Ans" not in line:
                    current_q['question'] += " " + line

    if current_q:
        while len(current_q['options']) < 4:
            current_q['options'].append("Option missing from PDF")
        all_questions.append(current_q)

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
    st.set_page_config(page_title="RRB JE Admin Portal", layout="wide")
    
    # Sidebar Management
    st.sidebar.title("📁 Repo Management")
    existing_files = fetch_files()
    if existing_files:
        file_to_del = st.sidebar.selectbox("Select paper to delete", existing_files)
        if st.sidebar.button("🗑️ Delete Selected"):
            if delete_from_git(file_to_del).status_code == 200:
                st.sidebar.success(f"Deleted {file_to_del}")
                st.rerun()
        if st.sidebar.button("🔥 WIPE REPOSITORY"):
            for f in existing_files: delete_from_git(f)
            st.sidebar.warning("All quizzes deleted!")
            st.rerun()
    else:
        st.sidebar.info("No files in repository.")

    t1, t2 = st.tabs(["📤 Bulk Upload & Preview", "✍️ Practice Quiz"])

    # TAB 1: UPLOADER
    with t1:
        st.header("Bulk PDF Uploader")
        uploaded_files = st.file_uploader("Upload RRB PDFs", type="pdf", accept_multiple_files=True)
        
        if uploaded_files:
            # Preview logic for the first file
            st.subheader(f"Previewing: {uploaded_files[0].name}")
            preview_qs = parse_rrb_pdf(uploaded_files[0])
            st.write(f"Total Questions Found: **{len(preview_qs)}**")
            
            # Checkbox to verify Q.4 fix specifically
            test_q = st.number_input("Test Question #", min_value=1, max_value=len(preview_qs), value=4)
            st.json(preview_qs[test_q-1])

            if st.button("🚀 Push All to GitHub"):
                p_bar = st.progress(0)
                for i, f in enumerate(uploaded_files):
                    qs = parse_rrb_pdf(f)
                    clean_name = re.sub(r'\.pdf$', '', f.name).replace(" ", "_") + ".json"
                    quiz_payload = {"metadata": {"file": f.name, "date": "16/12/2024"}, "questions": qs}
                    push_to_git(clean_name, json.dumps(quiz_payload, indent=4))
                    p_bar.progress((i + 1) / len(uploaded_files))
                st.success("Sync complete!")
                st.rerun()

    # TAB 2: QUIZ
    with t2:
        if existing_files:
            selected_quiz = st.selectbox("Select Practice Paper", existing_files)
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{selected_quiz}"
            res = requests.get(url, headers=get_headers())
            quiz_data = json.loads(base64.b64decode(res.json()['content']).decode())
            
            st.header(f"📖 {selected_quiz}")
            user_answers = {}
            for q in quiz_data["questions"]:
                st.write(f"**Q{q['id']}:** {q['question']}")
                user_answers[q['id']] = st.radio("Select Answer:", q['options'], key=f"{selected_quiz}_{q['id']}", index=None)
                st.divider()
            
            if st.button("Submit & Grade"):
                total = len(quiz_data["questions"])
                correct = sum(1 for q in quiz_data["questions"] if user_answers[q['id']] == q['answer'])
                st.sidebar.metric("Score", f"{correct}/{total}")
                st.sidebar.metric("Net Marks", f"{(correct - (total-correct)*(1/3)):.2f}")
        else:
            st.info("Upload your papers in the first tab to begin.")

if __name__ == "__main__":
    main()
