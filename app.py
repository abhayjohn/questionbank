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
    st.error("Please configure GITHUB_TOKEN, REPO_OWNER, and REPO_NAME in Streamlit Secrets.")
    st.stop()

# --- 2. UPDATED PARSING LOGIC ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            # Clean noise that interrupts option lists
            page_text = page.extract_text()
            page_text = re.sub(r'Adda247|A Google Play|INDIAN R|RAILWAY|Adda 247', '', page_text)
            full_text += page_text + "\n"

    blocks = re.split(r'Q\.\s*\d+', full_text)[1:]
    
    for idx, block in enumerate(blocks):
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        question_text, options, answer = "", [], ""

        for line in lines:
            # Capture options 1-4 and the text following them
            option_match = re.match(r'^([X✔]?\s*([1-4])\.)\s*(.*)', line)
            if option_match:
                clean_opt = option_match.group(3).strip()
                options.append(clean_opt)
                if '✔' in line or 'Ans' in line:
                    answer = clean_opt
            elif not options and "Ans" not in line and "Source" not in line:
                question_text += line + " "

        if question_text:
            while len(options) < 4:
                options.append("Option not found")
            all_questions.append({
                "id": idx + 1,
                "question": question_text.strip(),
                "options": options[:4],
                "answer": answer if answer else options[0]
            })
    return all_questions

# --- 3. GITHUB API LOGIC (PUSH, FETCH, DELETE) ---
def get_git_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

def push_to_git(filename, content):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    res = requests.get(url, headers=get_git_headers())
    sha = res.json().get('sha') if res.status_code == 200 else None
    payload = {"message": f"Update {filename}", "content": base64.b64encode(content.encode()).decode(), "branch": BRANCH}
    if sha: payload["sha"] = sha
    return requests.put(url, headers=get_git_headers(), json=payload)

def delete_from_git(filename):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{filename}"
    res = requests.get(url, headers=get_git_headers())
    if res.status_code == 200:
        sha = res.json().get('sha')
        payload = {"message": f"Delete {filename}", "sha": sha, "branch": BRANCH}
        return requests.delete(url, headers=get_git_headers(), json=payload)
    return res

def fetch_quiz_list():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes"
    res = requests.get(url, headers=get_git_headers())
    if res.status_code == 200:
        return [{"name": f['name'], "sha": f['sha']} for f in res.json() if f['name'].endswith('.json')]
    return []

# --- 4. UI COMPONENTS ---
def main():
    st.set_page_config(page_title="RRB Bulk Manager", layout="wide")
    
    # Sidebar Management
    st.sidebar.header("📁 Repository Manager")
    quiz_files = fetch_quiz_list()
    if quiz_files:
        file_to_del = st.sidebar.selectbox("Select file to delete", [f['name'] for f in quiz_files])
        if st.sidebar.button("🗑️ Delete Selected File"):
            resp = delete_from_git(file_to_del)
            if resp.status_code == 200:
                st.sidebar.success("Deleted!")
                st.rerun()
        
        if st.sidebar.button("🔥 Clear All Quizzes"):
            for f in quiz_files:
                delete_from_git(f['name'])
            st.sidebar.success("Repository Wiped!")
            st.rerun()
    else:
        st.sidebar.info("No files to manage.")

    tab1, tab2 = st.tabs(["📤 Bulk Upload & Preview", "✍️ Practice Quiz"])

    with tab1:
        st.header("Bulk Upload")
        uploaded_files = st.file_uploader("Upload RRB PDFs", type="pdf", accept_multiple_files=True)
        
        if uploaded_files:
            # Preview the first file
            st.subheader(f"Preview: {uploaded_files[0].name}")
            preview_qs = parse_rrb_pdf(uploaded_files[0])
            if preview_qs:
                st.write(f"Found **{len(preview_qs)}** questions. First question options:")
                st.write(preview_qs[0]['options'])
            
            if st.button("🚀 Push All to GitHub"):
                for file in uploaded_files:
                    qs = parse_rrb_pdf(file)
                    clean_name = re.sub(r'\.pdf$', '', file.name).replace(" ", "_") + ".json"
                    quiz_data = {"metadata": {"exam": "RRB JE", "file": file.name}, "questions": qs}
                    push_to_git(clean_name, json.dumps(quiz_data, indent=4))
                st.success("All files uploaded!")
                st.rerun()

    with tab2:
        if quiz_files:
            selected_quiz = st.selectbox("Select a Paper", [f['name'] for f in quiz_files])
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/quizzes/{selected_quiz}"
            res = requests.get(url, headers=get_git_headers())
            data = json.loads(base64.b64decode(res.json()['content']).decode())
            
            for q in data["questions"]:
                st.write(f"**Q{q['id']}:** {q['question']}")
                st.radio("Options:", q['options'], key=f"{selected_quiz}_{q['id']}", index=None)
                st.divider()
        else:
            st.info("No quizzes found. Upload PDFs to begin.")

if __name__ == "__main__":
    main()
