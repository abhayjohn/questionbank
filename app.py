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

# --- 2. SUPER-STATE PARSER (Fixes Q.5, Q.32, and Options) ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    # Filters to remove noise that breaks question-option continuity
    noise_filters = ["Adda247", "Adda 247", "Google Play", "INDIAN R", "LWAY", "AILWAY", "Subject", "Test Prime"]

    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                for word in noise_filters:
                    text = text.replace(word, "")
                full_text += text + "\n"

    q_pattern = re.compile(r'Q\.(\d+)')
    # Captures options 1-4 regardless of leading symbols (X/✔)
    opt_pattern = re.compile(r'.*?([1-4])\.\s*(.*)')

    current_q = None
    lines = full_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line: continue

        q_match = q_pattern.match(line)
        if q_match:
            # Save the finished question block
            if current_q and current_q['question']:
                while len(current_q['options']) < 4:
                    current_q['options'].append("Option not detected")
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
            if opt_match and len(current_q['options']) < 4:
                # Ensure we are capturing options in 1, 2, 3, 4 order
                opt_text = opt_match.group(2).strip()
                current_q['options'].append(opt_text)
                if '✔' in line or 'Ans' in line:
                    current_q['answer'] = opt_text
            elif len(current_q['options']) < 4:
                # If 4 options aren't found yet, append text to question (bridges page breaks)
                if "Ans" not in line:
                    current_q['question'] += " " + line

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

# --- 4. STREAMLIT UI ---
def main():
    st.set_page_config(page_title="RRB Exam Master", layout="wide")
    
    # Sidebar Status
    st.sidebar.title("📊 Git Repository")
    quiz_files = fetch_files()
    st.sidebar.write(f"Total Papers: **{len(quiz_files)}**")
    
    if quiz_files:
        st.sidebar.divider()
        to_del = st.sidebar.selectbox("Manage Files", quiz_files)
        if st.sidebar.button("🗑️ Delete Selected"):
            delete_from_git(to_del)
            st.rerun()
        if st.sidebar.button("🔥 WIPE ALL"):
            for f in quiz_files: delete_from_git(f)
            st.rerun()

    tab1, tab2 = st.tabs(["📤 Bulk Upload", "✍️ Practice Quiz"])

    # TAB 1: CONVERTER & ANALYSIS
    with tab1:
        st.header("Exam PDF to JSON Converter")
        files = st.file_uploader("Upload RRB PDFs", type="pdf", accept_multiple_files=True)
        
        if files:
            # Show status for the first file
            data = parse_rrb_pdf(files[0])
            count = len(data)
            st.subheader(f"Analysis: {files[0].name}")
            
            c1, c2 = st.columns(2)
            c1.metric("Questions Found", f"{count}/100")
            if count < 100:
                missing = [i for i in range(1, 101) if i not in [q['id'] for q in data]]
                c2.error(f"Missing IDs: {missing}")
            else:
                c2.success("Perfect! 100/100 found.")
            
            if st.button("🚀 Push to GitHub"):
                for f in files:
                    qs = parse_rrb_pdf(f)
                    fname = f.name.replace(" ", "_").replace(".pdf", ".json")
                    push_to_git(fname, json.dumps({"questions": qs}, indent=4))
                st.success("Successfully synced all files!")
                st.rerun()

    # TAB 2: QUIZ
    with tab2:
        if quiz_files:
            selected = st.selectbox("Select Paper", quiz_files)
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{selected}"
            res = requests.get(url, headers=get_headers())
            quiz = json.loads(base64.b64decode(res.json()['content']).decode())
            
            for q in quiz["questions"]:
                st.write(f"**Q{q['id']}:** {q['question']}")
                st.radio("Options", q['options'], key=f"{selected}_{q['id']}", index=None)
                st.divider()
        else:
            st.info("Upload PDFs in Tab 1 to start.")

if __name__ == "__main__":
    main()
