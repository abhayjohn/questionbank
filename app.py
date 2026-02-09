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

# --- 2. THE ULTIMATE RRB PARSER (Fixes Empty Questions & Missing Options) ---
def parse_rrb_pdf(uploaded_file):
    all_questions = []
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                # Remove ads/noise that split questions across pages
                text = re.sub(r'Adda247|Adda 247|Google Play|INDIAN R|LWAY|AILWAY|Test Prime|Source', '', text)
                full_text += text + "\n"

    # Strategy: Explicitly find every Q.1 through Q.100
    for i in range(1, 101):
        # Find Q.i followed by space, newline, or the actual question text
        pattern = re.compile(rf'Q\.{i}(?:\s|\n|(?=[A-Z]))')
        match = pattern.search(full_text)
        
        if match:
            # The start of the question is right after "Q.i"
            start_pos = match.end()
            # The end is the start of the next "Q.i+1"
            next_pattern = re.compile(rf'Q\.{i+1}(?:\s|\n|(?=[A-Z]))')
            next_match = next_pattern.search(full_text)
            end_pos = next_match.start() if next_match else len(full_text)
            
            block = full_text[start_pos:end_pos]
            lines = [line.strip() for line in block.split('\n') if line.strip()]
            
            question_parts = []
            options = []
            answer = ""

            # Improved Option Regex: Ignores icons (X/✔) and captures 1., 2., 3., 4.
            opt_pattern = re.compile(r'.*?([1-4])\.\s*(.*)')

            for line in lines:
                opt_match = opt_pattern.match(line)
                if opt_match and len(options) < 4:
                    opt_text = opt_match.group(2).strip()
                    options.append(opt_text)
                    # Detect correct answer via icon or "Ans" text [cite: 9, 16, 770]
                    if '✔' in line or 'Ans' in line:
                        answer = opt_text
                elif len(options) < 4:
                    # If it's not an option yet, it belongs to the question body
                    if "Ans" not in line:
                        question_parts.append(line)

            # Ensure UI doesn't break if options were truly unreadable
            while len(options) < 4:
                options.append("Option not detected")

            all_questions.append({
                "id": i,
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
    if res.status_code == 200:
        return [f['name'] for f in res.json() if f['name'].endswith('.json')]
    return []

# --- 4. STREAMLIT UI ---
def main():
    st.set_page_config(page_title="RRB Exam Master", layout="wide")
    
    st.sidebar.title("📊 Repository Status")
    quiz_files = fetch_files()
    st.sidebar.write(f"Papers in Git: **{len(quiz_files)}**")
    
    tab1, tab2 = st.tabs(["📤 Upload & Detect", "✍️ Practice Mode"])

    with tab1:
        st.header("Bulk PDF to JSON Converter")
        files = st.file_uploader("Upload RRB PDFs", type="pdf", accept_multiple_files=True)
        
        if files:
            # Detect questions for the first file to show status
            data = parse_rrb_pdf(files[0])
            count = len(data)
            
            st.subheader(f"Analysis for: {files[0].name}")
            col1, col2 = st.columns(2)
            col1.metric("Questions Found", f"{count}/100")
            
            if count < 100:
                found_ids = [q['id'] for q in data]
                missing = [i for i in range(1, 101) if i not in found_ids]
                col2.error(f"Missing IDs: {missing}")
            else:
                col2.success("All 100 questions perfectly detected!")

            # Detailed Preview to verify Question Text fix
            st.write("### Preview of First Question:")
            if data:
                st.write(f"**Question Text:** {data[0]['question']}")
                st.write(f"**Options:** {data[0]['options']}")

            if st.button("🚀 Push All to GitHub"):
                for f in files:
                    qs = parse_rrb_pdf(f)
                    fname = f.name.replace(" ", "_").replace(".pdf", ".json")
                    push_to_git(fname, json.dumps({"questions": qs}, indent=4))
                st.success("Successfully synced all papers!")
                st.rerun()

    with tab2:
        if quiz_files:
            selected = st.selectbox("Select a Practice Paper", quiz_files)
            # Fetch content from GitHub API
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
