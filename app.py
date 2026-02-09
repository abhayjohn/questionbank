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

# --- 2. GLOBAL SEARCH PARSER (Ensures 100 Questions) ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                # Scrub noise that breaks the link between Q.5/Q.32 and their options
                text = re.sub(r'Adda247|Adda 247|Google Play|INDIAN R|LWAY|AILWAY|Subject|Test Prime|Source', '', text)
                full_text += text + "\n"

    # Strategy: Find the index of every "Q.1", "Q.2" ... "Q.100" in the text
    indices = []
    for i in range(1, 101):
        # Look for "Q.1 " or "Q.1\n" to avoid matching "Q.10" when looking for "Q.1"
        pattern = re.compile(rf'Q\.{i}\s')
        match = pattern.search(full_text)
        if match:
            indices.append((i, match.start()))

    # Sort indices just in case extraction was out of order
    indices.sort(key=lambda x: x[1])

    for i in range(len(indices)):
        q_num, start_pos = indices[i]
        # End position is the start of the next question, or the end of the text
        end_pos = indices[i+1][1] if i+1 < len(indices) else len(full_text)
        
        block = full_text[start_pos:end_pos]
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        
        question_parts = []
        options = []
        answer = ""

        # Regex for options: ignores leading icons like X or ✔
        opt_pattern = re.compile(r'.*?([1-4])\.\s*(.*)')

        for line in lines:
            # Skip the "Q.X" line itself for the question text
            if line.startswith(f"Q.{q_num}"):
                question_parts.append(line.replace(f"Q.{q_num}", "").strip())
                continue

            opt_match = opt_pattern.match(line)
            if opt_match and len(options) < 4:
                opt_text = opt_match.group(2).strip()
                options.append(opt_text)
                if '✔' in line or 'Ans' in line:
                    answer = opt_text
            elif len(options) < 4:
                if "Ans" not in line:
                    question_parts.append(line)

        # Pad missing options to keep the UI consistent
        while len(options) < 4:
            options.append("Option not detected")

        all_questions.append({
            "id": q_num,
            "question": " ".join(question_parts).strip(),
            "options": options,
            "answer": answer if answer else options[0]
        })

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
    st.set_page_config(page_title="RRB 100-Question Portal", layout="wide")
    
    st.sidebar.title("📊 Repo Status")
    quiz_files = fetch_files()
    st.sidebar.write(f"Papers in Git: **{len(quiz_files)}**")
    
    if quiz_files:
        to_del = st.sidebar.selectbox("Delete Paper", quiz_files)
        if st.sidebar.button("🗑️ Delete"):
            delete_from_git(to_del)
            st.rerun()
    
    tab1, tab2 = st.tabs(["📤 Upload & Detect", "✍️ Practice Mode"])

    with tab1:
        st.header("Bulk PDF to JSON")
        files = st.file_uploader("Upload RRB PDFs", type="pdf", accept_multiple_files=True)
        
        if files:
            data = parse_rrb_pdf(files[0])
            count = len(data)
            st.subheader(f"Analysis: {files[0].name}")
            st.metric("Questions Found", f"{count}/100")
            
            if count < 100:
                found_ids = [q['id'] for q in data]
                missing = [i for i in range(1, 101) if i not in found_ids]
                st.error(f"Missing IDs: {missing}")
            else:
                st.success("All 100 questions detected!")

            if st.button("🚀 Push to GitHub"):
                for f in files:
                    qs = parse_rrb_pdf(f)
                    fname = f.name.replace(" ", "_").replace(".pdf", ".json")
                    push_to_git(fname, json.dumps({"questions": qs}, indent=4))
                st.success("Synced!")
                st.rerun()

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

if __name__ == "__main__":
    main()
