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
    st.error("Secrets not configured! Add GITHUB_TOKEN, REPO_OWNER, and REPO_NAME to Streamlit Secrets.")
    st.stop()

# --- 2. INFINITE-BUFFER PARSER (Fixes Q.5, Q.32 across page breaks) ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    # Filters to scrub out page-break noise that confuses the parser
    noise_filters = [
        "Adda247", "Adda 247", "Google Play", "INDIAN R", 
        "LWAY", "AILWAY", "Subject", "Test Prime", "Source"
    ]

    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                # Remove common header/footer strings immediately
                for word in noise_filters:
                    text = text.replace(word, "")
                full_text += text + "\n"

    # Pattern for Q.1, Q.2, etc.
    q_pattern = re.compile(r'Q\.(\d+)')
    # Pattern for 1., 2., 3., 4. (ignoring leading X or ✔ symbols)
    opt_pattern = re.compile(r'.*?([1-4])\.\s*(.*)')

    current_q = None
    lines = full_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line: continue

        q_match = q_pattern.match(line)
        if q_match:
            # Save the previous question if it exists
            if current_q and current_q['question']:
                while len(current_q['options']) < 4:
                    current_q['options'].append("Option not detected")
                all_questions.append(current_q)
            
            # Start a new question state
            current_q = {
                "id": int(q_match.group(1)),
                "question": line.replace(q_match.group(0), "").strip(),
                "options": [],
                "answer": ""
            }
            continue

        if current_q:
            opt_match = opt_pattern.match(line)
            if opt_match and len(current_q['options']) < 4:
                opt_text = opt_match.group(2).strip()
                current_q['options'].append(opt_text)
                # Correct answer detection via Green Tick or Ans keyword
                if '✔' in line or 'Ans' in line:
                    current_q['answer'] = opt_text
            elif len(current_q['options']) < 4:
                # If we haven't found 4 options yet, any other text is question body
                if "Ans" not in line:
                    current_q['question'] += " " + line

    # Finalize the last question in the document
    if current_q:
        while len(current_q['options']) < 4:
            current_q['options'].append("Option not detected")
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
    payload = {"message": f"Sync {filename}", "content": base64.b64encode(content.encode()).decode(), "branch": BRANCH}
    if sha: payload["sha"] = sha
    return requests.put(url, headers=get_headers(), json=payload)

def fetch_files():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes"
    res = requests.get(url, headers=get_headers())
    return [f['name'] for f in res.json() if f['name'].endswith('.json')] if res.status_code == 200 else []

def delete_from_git(filename):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    res = requests.get(url, headers=get_headers())
    if res.status_code == 200:
        sha = res.json().get('sha')
        payload = {"message": f"Delete {filename}", "sha": sha, "branch": BRANCH}
        return requests.delete(url, headers=get_headers(), json=payload)
    return res

# --- 4. STREAMLIT INTERFACE ---
def main():
    st.set_page_config(page_title="RRB Exam Portal", layout="wide")
    
    # Sidebar: Repository Stats
    st.sidebar.title("📊 Repository Status")
    quiz_files = fetch_files()
    st.sidebar.write(f"Papers in Git: **{len(quiz_files)}**")
    
    if quiz_files:
        st.sidebar.divider()
        to_del = st.sidebar.selectbox("File Management", quiz_files)
        if st.sidebar.button("🗑️ Delete Paper"):
            delete_from_git(to_del)
            st.rerun()
        if st.sidebar.button("🔥 WIPE REPO"):
            for f in quiz_files: delete_from_git(f)
            st.rerun()

    tab1, tab2 = st.tabs(["📤 Bulk Upload & Check", "✍️ Practice Mode"])

    # TAB 1: CONVERTER & ANALYSIS
    with tab1:
        st.header("Convert Exam PDFs to Practice JSONs")
        files = st.file_uploader("Upload RRB PDFs", type="pdf", accept_multiple_files=True)
        
        if files:
            # Analyze the first file for question integrity
            data = parse_rrb_pdf(files[0])
            count = len(data)
            st.subheader(f"Data Analysis: {files[0].name}")
            
            c1, c2 = st.columns(2)
            c1.metric("Questions Detected", f"{count}/100")
            
            if count < 100:
                # Find exactly which IDs are missing
                found_ids = [q['id'] for q in data]
                missing = [i for i in range(1, 101) if i not in found_ids]
                c2.error(f"Missing IDs: {missing}")
            else:
                c2.success("Perfect capture! 100/100 questions found.")
            
            if st.button("🚀 Push to GitHub"):
                for f in files:
                    qs = parse_rrb_pdf(f)
                    fname = f.name.replace(" ", "_").replace(".pdf", ".json")
                    push_to_git(fname, json.dumps({"questions": qs}, indent=4))
                st.success("Successfully synced all papers to Git!")
                st.rerun()

    # TAB 2: QUIZ RENDERING
    with tab2:
        if quiz_files:
            selected = st.selectbox("Select a Practice Paper", quiz_files)
            # Fetch content from GitHub
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{selected}"
            res = requests.get(url, headers=get_headers())
            content = json.loads(base64.b64decode(res.json()['content']).decode())
            
            st.title(f"✍️ {selected}")
            user_answers = {}
            for q in content["questions"]:
                st.write(f"**Q{q['id']}:** {q['question']}")
                user_answers[q['id']] = st.radio("Options", q['options'], key=f"{selected}_{q['id']}", index=None)
                st.divider()
            
            if st.button("Finish & Show Results"):
                score = sum(1 for q in content["questions"] if user_answers[q['id']] == q['answer'])
                st.sidebar.metric("Final Score", f"{score}/{len(content['questions'])}")
                st.sidebar.caption("Negative Marking: 1/3 deduction per wrong answer")
        else:
            st.info("Upload PDFs in Tab 1 to start.")

if __name__ == "__main__":
    main()
