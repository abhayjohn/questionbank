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

# --- 2. SYMBOL-AGNOSTIC PARSER (Fixes Missing Options & Question Count) ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                # Remove ads/noise that split questions across pages
                text = re.sub(r'Adda247|Adda 247|Google Play|INDIAN RAILWAYS|RAILWAY|Test Prime', '', text)
                full_text += text + "\n"

    # Regex to find Q. followed by a number
    q_pattern = re.compile(r'Q\.(\d+)')
    # IMPROVED Regex: Ignores leading symbols (X/✔) and finds "1." through "4."
    opt_pattern = re.compile(r'.*?([1-4])\.\s*(.*)')

    current_q = None
    
    for line in full_text.split('\n'):
        line = line.strip()
        if not line: continue

        q_match = q_pattern.match(line)
        if q_match:
            # Finalize previous question
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
                opt_num = opt_match.group(1)
                opt_text = opt_match.group(2).strip()
                
                # Add only if we haven't reached 4 options
                if len(current_q['options']) < 4:
                    current_q['options'].append(opt_text)
                    # Detect correct answer via icon or "Ans" text
                    if '✔' in line or 'Ans' in line:
                        current_q['answer'] = opt_text
            else:
                # If we don't have 4 options, this line is part of the question body
                if len(current_q['options']) < 4 and "Ans" not in line:
                    current_q['question'] += " " + line

    # Add last question
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
    payload = {"message": f"Sync {filename}", "content": base64.b64encode(content.encode()).decode(), "branch": BRANCH}
    if sha: payload["sha"] = sha
    return requests.put(url, headers=get_headers(), json=payload)

def fetch_files():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes"
    res = requests.get(url, headers=get_headers())
    if res.status_code == 200:
        return [f['name'] for f in res.json() if f['name'].endswith('.json')]
    return []

def delete_from_git(filename):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    res = requests.get(url, headers=get_headers())
    if res.status_code == 200:
        sha = res.json().get('sha')
        payload = {"message": f"Delete {filename}", "sha": sha, "branch": BRANCH}
        return requests.delete(url, headers=get_headers(), json=payload)
    return res

# --- 4. UI INTERFACE ---
def main():
    st.set_page_config(page_title="RRB Exam Master", layout="wide")
    
    # Sidebar: Repository Status & Management
    st.sidebar.title("📊 Repository Status")
    quiz_files = fetch_files()
    st.sidebar.write(f"Papers in Git: **{len(quiz_files)}**")
    
    if quiz_files:
        st.sidebar.divider()
        st.sidebar.subheader("Management")
        to_del = st.sidebar.selectbox("Select Paper", quiz_files)
        if st.sidebar.button("🗑️ Delete Paper"):
            if delete_from_git(to_del).status_code == 200:
                st.sidebar.success("Deleted!")
                st.rerun()
        if st.sidebar.button("🔥 WIPE ALL"):
            for f in quiz_files: delete_from_git(f)
            st.rerun()

    tab1, tab2 = st.tabs(["📤 Upload & Status", "✍️ Practice Quiz"])

    # TAB 1: CONVERTER & STATUS COUNTER
    with tab1:
        st.header("Bulk PDF Converter")
        files = st.file_uploader("Upload RRB PDFs", type="pdf", accept_multiple_files=True)
        
        if files:
            # Status Counter for the first file in upload list
            preview_data = parse_rrb_pdf(files[0])
            total_found = len(preview_data)
            
            st.subheader(f"Status for: {files[0].name}")
            col1, col2 = st.columns(2)
            col1.metric("Questions Detected", f"{total_found}/100")
            
            if total_found < 100:
                col2.warning("Some questions were not detected.")
                # Identify missing IDs
                found_ids = [q['id'] for q in preview_data]
                missing = [i for i in range(1, 101) if i not in found_ids]
                if missing:
                    st.error(f"Missing Question IDs: {missing}")
            else:
                col2.success("Perfect capture! All 100 questions found.")

            if st.button("🚀 Push All to GitHub"):
                p_bar = st.progress(0)
                for i, f in enumerate(files):
                    qs = parse_rrb_pdf(f)
                    clean_name = re.sub(r'\.pdf$', '', f.name).replace(" ", "_") + ".json"
                    quiz_payload = {"metadata": {"file": f.name, "q_count": len(qs)}, "questions": qs}
                    push_to_git(clean_name, json.dumps(quiz_payload, indent=4))
                    p_bar.progress((i + 1) / len(files))
                st.success("Successfully synced all papers!")
                st.rerun()

    # TAB 2: QUIZ RENDERING
    with tab2:
        if quiz_files:
            selected_quiz = st.selectbox("Select a Practice Paper", quiz_files)
            # Fetch content from Git
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{selected_quiz}"
            res = requests.get(url, headers=get_headers())
            data = json.loads(base64.b64decode(res.json()['content']).decode())
            
            st.title(f"📖 {selected_quiz}")
            user_answers = {}
            for q in data["questions"]:
                st.write(f"**Q{q['id']}:** {q['question']}")
                user_answers[q['id']] = st.radio("Options:", q['options'], key=f"{selected_quiz}_{q['id']}", index=None)
                st.divider()
            
            if st.button("Finish & Grade"):
                score = sum(1 for q in data["questions"] if user_answers[q['id']] == q['answer'])
                st.sidebar.metric("Your Score", f"{score}/{len(data['questions'])}")
        else:
            st.info("Upload and process PDFs in Tab 1 to see them here.")

if __name__ == "__main__":
    main()
