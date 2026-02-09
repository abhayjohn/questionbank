import streamlit as st
import pdfplumber
import json
import base64
import requests
import re

# --- 1. ACCESS SECRETS ---
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"].strip()
    REPO_OWNER = st.secrets["REPO_OWNER"].strip()
    REPO_NAME = st.secrets["REPO_NAME"].strip()
    BRANCH = st.secrets.get("BRANCH", "main").strip()
except Exception:
    st.error("Secrets not configured! Add GITHUB_TOKEN, REPO_OWNER, and REPO_NAME to Streamlit Secrets.")
    st.stop()

# --- 2. UPDATED PARSER (Fixes Missing Question Text in Q.5) ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                # Remove ads/noise that split questions
                text = re.sub(r'Adda247|Adda 247|Google Play|INDIAN R|LWAY|AILWAY|Test Prime|Source', '', text)
                full_text += text + "\n"

    # Strategy: Explicitly find every Q.1 through Q.100
    for i in range(1, 101):
        # Improved Regex: Capture the Q number and everything until the next Q number
        pattern = re.compile(rf'Q\.{i}(?:\s|\n|(?=[A-Z0-9]))')
        match = pattern.search(full_text)
        
        if match:
            start_pos = match.end()
            next_pattern = re.compile(rf'Q\.{i+1}(?:\s|\n|(?=[A-Z0-9]))')
            next_match = next_pattern.search(full_text)
            end_pos = next_match.start() if next_match else len(full_text)
            
            block = full_text[start_pos:end_pos]
            lines = [line.strip() for line in block.split('\n') if line.strip()]
            
            question_parts = []
            options = []
            answer = ""

            # Regex for options: ignores icons (X/✔)
            opt_pattern = re.compile(r'.*?([1-4])\.\s*(.*)')

            for line in lines:
                opt_match = opt_pattern.match(line)
                if opt_match and len(options) < 4:
                    opt_text = opt_match.group(2).strip()
                    options.append(opt_text)
                    if '✔' in line or 'Ans' in line:
                        answer = opt_text
                elif len(options) < 4:
                    # Capture everything as question text, including math symbols
                    if "Ans" not in line:
                        question_parts.append(line)

            while len(options) < 4:
                options.append("Option not detected")

            # If question text is still empty, attempt a 'deep scan' for that block
            q_text = " ".join(question_parts).strip()
            if not q_text and lines:
                q_text = lines[0] # Fallback to first available line

            all_questions.append({
                "id": i,
                "question": q_text,
                "options": options,
                "answer": answer if answer else (options[0] if options else "")
            })

    return all_questions

# --- 3. GITHUB API HELPERS ---
def get_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

def fetch_files():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes"
    res = requests.get(url, headers=get_headers())
    if res.status_code == 200:
        return [f['name'] for f in res.json() if f['name'].endswith('.json')]
    return []

def push_to_git(filename, content):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    res = requests.get(url, headers=get_headers())
    sha = res.json().get('sha') if res.status_code == 200 else None
    payload = {"message": f"Sync {filename}", "content": base64.b64encode(content.encode()).decode(), "branch": BRANCH}
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

# --- 4. MAIN UI ---
def main():
    st.set_page_config(page_title="RRB Exam Master", layout="wide")
    
    # Sidebar Management
    st.sidebar.title("📊 Repository Management")
    quiz_files = fetch_files()
    st.sidebar.write(f"Papers in Git: **{len(quiz_files)}**")
    
    if quiz_files:
        st.sidebar.divider()
        file_to_del = st.sidebar.selectbox("Select Paper to Delete", quiz_files)
        if st.sidebar.button("🗑️ Delete Selected"):
            if delete_from_git(file_to_del).status_code == 200:
                st.sidebar.success(f"Deleted {file_to_del}")
                st.rerun()
        if st.sidebar.button("🔥 WIPE ALL QUIZZES"):
            for f in quiz_files: delete_from_git(f)
            st.rerun()

    tab1, tab2 = st.tabs(["📤 Upload & Detect", "✍️ Practice Quiz"])

    # TAB 1: CONVERTER & ANALYSIS
    with tab1:
        st.header("Bulk PDF to JSON Converter")
        files = st.file_uploader("Upload RRB PDFs", type="pdf", accept_multiple_files=True)
        
        if files:
            data = parse_rrb_pdf(files[0])
            count = len(data)
            st.subheader(f"Analysis for: {files[0].name}")
            
            c1, c2 = st.columns(2)
            c1.metric("Questions Found", f"{count}/100")
            
            if count < 100:
                missing = [i for i in range(1, 101) if i not in [q['id'] for q in data]]
                c2.error(f"Missing IDs: {missing}")
            else:
                c2.success("Perfect capture! All 100 questions found.")

            if st.button("🚀 Push All to GitHub"):
                for f in files:
                    qs = parse_rrb_pdf(f)
                    fname = f.name.replace(" ", "_").replace(".pdf", ".json")
                    push_to_git(fname, json.dumps({"questions": qs}, indent=4))
                st.success("Successfully synced all papers!")
                st.rerun()

    # TAB 2: QUIZ RENDERING
    with tab2:
        if quiz_files:
            selected = st.selectbox("Select a Practice Paper", quiz_files)
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{selected}"
            res = requests.get(url, headers=get_headers())
            content = json.loads(base64.b64decode(res.json()['content']).decode())
            
            for q in content["questions"]:
                st.write(f"**Q{q['id']}:** {q['question']}")
                st.radio("Options:", q['options'], key=f"{selected}_{q['id']}", index=None)
                st.divider()
        else:
            st.info("No quizzes found. Upload PDFs in Tab 1.")

if __name__ == "__main__":
    main()
