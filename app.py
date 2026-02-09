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

# --- 2. ADVANCED PARSER WITH AUTO-RETRY ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                # Remove common header/footer noise
                text = re.sub(r'Adda247|Adda 247|Google Play|INDIAN RAILWAYS|RAILWAY|Test Prime', '', text)
                full_text += text + "\n"

    # Regex patterns
    q_pattern = re.compile(r'Q\.(\d+)')
    # Handles options even with leading symbols or icons
    opt_pattern = re.compile(r'.*?([1-4])\.\s*(.*)')

    def extract_with_logic(text_block):
        extracted = []
        current_q = None
        for line in text_block.split('\n'):
            line = line.strip()
            if not line: continue
            
            q_match = q_pattern.match(line)
            if q_match:
                if current_q and current_q['question']:
                    while len(current_q['options']) < 4:
                        current_q['options'].append("Option not detected")
                    extracted.append(current_q)
                current_q = {"id": int(q_match.group(1)), "question": line.replace(q_match.group(0), "").strip(), "options": [], "answer": ""}
                continue

            if current_q:
                opt_match = opt_pattern.match(line)
                if opt_match and len(current_q['options']) < 4:
                    opt_text = opt_match.group(2).strip()
                    current_q['options'].append(opt_text)
                    if '✔' in line or 'Ans' in line: current_q['answer'] = opt_text
                elif len(current_q['options']) < 4 and "Ans" not in line:
                    current_q['question'] += " " + line
        
        if current_q:
            while len(current_q['options']) < 4: current_q['options'].append("Option not detected")
            extracted.append(current_q)
        return extracted

    # Pass 1: Standard Extraction
    all_questions = extract_with_logic(full_text)
    
    # Auto-Retry Logic: If count < 100, try a more aggressive regex for question markers
    if len(all_questions) < 100:
        # Fallback regex for questions that might be missing the 'Q.' prefix in some extractions
        q_pattern = re.compile(r'(?:^|\n)(\d+)\s*\n') 
        retry_questions = extract_with_logic(full_text)
        if len(retry_questions) > len(all_questions):
            all_questions = retry_questions

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
    
    # Sidebar: Repository Management
    st.sidebar.title("📊 Repo Management")
    quiz_files = fetch_files()
    st.sidebar.write(f"Papers in Git: **{len(quiz_files)}**")
    
    if quiz_files:
        to_del = st.sidebar.selectbox("Select Paper", quiz_files)
        if st.sidebar.button("🗑️ Delete Selected"):
            if delete_from_git(to_del).status_code == 200:
                st.sidebar.success("Deleted!")
                st.rerun()
        if st.sidebar.button("🔥 WIPE ALL"):
            for f in quiz_files: delete_from_git(f)
            st.rerun()

    tab1, tab2 = st.tabs(["📤 Upload & Analysis", "✍️ Practice Mode"])

    with tab1:
        st.header("Exam PDF Processor")
        files = st.file_uploader("Upload RRB PDFs", type="pdf", accept_multiple_files=True)
        
        if files:
            # Analyze the first file for status
            data = parse_rrb_pdf(files[0])
            count = len(data)
            
            st.subheader(f"Analysis: {files[0].name}")
            col1, col2 = st.columns(2)
            col1.metric("Questions Found", f"{count}/100")
            
            if count < 100:
                found_ids = [q['id'] for q in data]
                missing = [i for i in range(1, 101) if i not in found_ids]
                st.error(f"Missing IDs: {missing}")
            else:
                st.success("Full 100-question set detected!")

            if st.button("🚀 Push to GitHub"):
                for f in files:
                    qs = parse_rrb_pdf(f)
                    fname = f.name.replace(" ", "_").replace(".pdf", ".json")
                    push_to_git(fname, json.dumps({"questions": qs}, indent=4))
                st.success("Synced successfully!")
                st.rerun()

    with tab2:
        if quiz_files:
            selected = st.selectbox("Choose Paper", quiz_files)
            # Fetch from Git logic...
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
