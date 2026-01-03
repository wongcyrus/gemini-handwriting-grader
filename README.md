# Gemini-Handwriting-Grader
As an educator, grading tests and assignments is a challenging and time-consuming task. The process involves several steps, such as collecting all completed scripts, reviewing the standard answers and marking for each question, assigning marks, and repeating the process for each student. Once all questions have been marked, the total score for each student must be calculated and entered into a spreadsheet. Finally, the scored scripts are returned to the students.

The current process is quite tedious and involves several unnecessary steps, such as flipping through papers, calculating total marks, and manually entering them into a spreadsheet. Reviewing standard answers and grading each question individually is also quite inefficient, as educators often have to repeat the process until they can memorize the marking scheme. Furthermore, this approach can sometimes result in unfair grading, as educators may not review all student answers for each question at the same time. To address this issue, some educators opt to score each question individually, but this requires flipping through the script multiple times, adding to the workload.

The process is not only physically exhausting but can also result in long-term back and neck pain for educators. Moreover, this process does not necessarily contribute to student learning. The issue at hand could be resolved with the application of machine learning and AI methods. Firstly, automating the process as much as possible would eliminate the need for manual paper flipping. Secondly, utilizing AI processing and analysis would facilitate a more efficient review of students' answers, potentially reducing the workload for educators. Lastly, it would ensure that answers are scored objectively by concealing personal identity.

This version is not reliant on cloud services and can be utilized by all educators through the free GitHub CodeSpaces platform.

## How it Works

This project automates the grading process using a series of Jupyter notebooks that leverage Google's Gemini AI. The workflow is as follows:

1.  **Generate Answer Sheets**: Creates personalized answer sheets for each student from a roster.
2.  **Extract Marking Scheme**: Parses a `.docx` marking scheme into a structured Excel file using Gemini.
3.  **Define Answer Regions**: Converts the scanned exam PDF into images and allows the user to define bounding boxes for each answer area.
4.  **AI-Powered Scoring**: Performs OCR on the handwritten answers, grades them against the marking scheme using Gemini, and builds a web interface for review.
5.  **Review and Finalize**: The educator reviews the AI-generated scores, makes adjustments in the web UI, and finalizes the marks.
6.  **Package Results**: Generates comprehensive reports, creates individually scored PDF files for each student, and packages all outputs.
7.  **Email Scores**: Sends personalized emails to each student with their score, a performance summary, and the annotated script attached.

## Setup and Input Files

Before running the notebooks, you need to prepare the following files. It is recommended to copy the examples from the `sample/` directory, customize them, and place them in the `data/` directory.

Let `<exam_prefix>` be the base name for your exam (e.g., `VTC Test`).

### 1. Scanned Student Scripts
-   **File**: `data/<exam_prefix>.pdf`
-   **Description**: A single PDF file containing all the scanned, handwritten student answer sheets.

### 2. Student Roster
-   **File**: `data/<exam_prefix> Name List.xlsx`
-   **Description**: An Excel file listing your students. It **must** contain `ID`, `NAME`, and `CLASS` columns.
-   **Template**: `sample/VTC Test Name List.xlsx`

### 3. Answer Sheet Template
-   **File**: `data/<exam_prefix> Answer Sheet.docx`
-   **Description**: A Microsoft Word document that will be used as a template to generate individual answer sheets for printing. This is used in Step 1. It should contain `Name:`, `Student ID:`, and `Class:` placeholders.
-   **Template**: `sample/VTC Test Answer Sheet.docx`

### 4. Marking Scheme
-   **File**: `data/<exam_prefix> Marking Scheme.docx`
-   **Description**: A Microsoft Word document containing the questions, standard answers, and marking rubric. This will be processed by Gemini in Step 2.
-   **Template**: `sample/VTC Test Marking Scheme.docx`

### 5. Email Configuration
-   **File**: `smtp.config` (in the project root)
-   **Description**: Your SMTP server credentials for sending emails in Step 7.
-   **Template**: `smtp-template.config`. Rename this file to `smtp.config` and fill in your details.

## Workflow: Notebook by Notebook

Follow these steps in order by running the Jupyter notebooks located in the `notebbooks/` directory. In each notebook, remember to set the `prefix` variable to match your `<exam_prefix>`.

### Step 1: Generate Answer Sheets (`step1_generate_answer_sheet.ipynb`)
- **Purpose**: Creates personalized answer sheets for each student, ready for printing.
- **Inputs**:
    - `data/<exam_prefix> Name List.xlsx`
    - `data/<exam_prefix> Answer Sheet.docx`
- **Output**:
    - `data/<exam_prefix> Answer Sheets Combined.pdf`: A single, combined PDF of all student answer sheets.

### Step 2: Extract Marking Scheme (`step2_generate_marking_scheme_excel.ipynb`)
- **Purpose**: Uses Gemini to parse the `.docx` marking scheme and convert it into a structured Excel file.
- **Input**:
    - `data/<exam_prefix> Marking Scheme.docx`
- **Output**:
    - `data/<exam_prefix> Marking Scheme.xlsx`: A structured Excel file containing the rubric, which will be used for AI grading in Step 4.

### Step 3: Define Answer Regions (`step3_question_annotations.ipynb`)
- **Purpose**: Identify the location of each answer on the scanned exam pages.
- **Input**:
    - `data/<exam_prefix>.pdf` (the scanned, completed student scripts)
- **Process**:
    1.  Converts the PDF into JPEG images.
    2.  Uses Gemini to auto-detect bounding boxes for each answer.
    3.  Provides an interactive widget for you to review and adjust the bounding boxes.
- **Outputs**:
    - `marking_form/<exam_prefix>/images/`: JPEG image of each scanned page.
    - `marking_form/<exam_prefix>/annotations/annotations.json`: The final bounding box data.

### Step 4: Scoring Preprocessing (`step4_scoring_preprocessing.ipynb`)
- **Purpose**: Performs OCR, grades the answers with Gemini, and generates a web UI for the educator to review the results.
- **Inputs**:
    - `marking_form/<exam_prefix>/images/*.jpg`
    - `marking_form/<exam_prefix>/annotations/annotations.json`
    - `data/<exam_prefix> Marking Scheme.xlsx`
- **Output**:
    - A local website in `marking_form/<exam_prefix>/`. You can launch it by running `server.py` and access it in your browser to review, adjust, and finalize scores. When you save marks in the UI, `mark.json` files are created for each question.
    - `cache/`: Contains cached Gemini API responses for OCR and grading to speed up reruns.

### Step 5: Post-Scoring Checks (`step5_post_scoring_checks.ipynb`)
- **Purpose**: Verifies that all answers have been scored and checks for data inconsistencies before final packaging.
- **Inputs**:
    - `marking_form/<exam_prefix>/questions/**/mark.json`
    - `data/<exam_prefix> Name List.xlsx`
- **Process**:
    - Confirms every question has a mark for every student.
    - Verifies student IDs from the grading UI against the name list.
    - Cleans up temporary files generated by the web UI.

### Step 6: Post-Scoring Packaging (`step6_scoring_postprocessing.ipynb`)
- **Purpose**: Generates all final reports, annotated PDFs, and archives.
- **Inputs**:
    - All data from the previous steps, primarily `mark.json` files.
- **Outputs**: See the **Key Outputs** section below for a detailed list of generated files, including score reports and marked scripts.

### Step 7: Email Scores (`step7_email_score.ipynb`)
- **Purpose**: Sends a personalized email to each student with their score, a performance report, and their marked script.
- **Inputs**:
    - `smtp.config`
    - `marking_form/<exam_prefix>/marked/scripts/details_score_report.xlsx`
    - `marking_form/<exam_prefix>/marked/pdfs/<ID>.pdf`

## Key Outputs

All outputs are generated within the `marking_form/<exam_prefix>/` directory, organized by exam prefix.

-   **Excel Score Reports**:
    -   `marking_form/<exam_prefix>/marked/scripts/details_score_report.xlsx`: A comprehensive multi-sheet workbook containing final marks, captured answers, AI reasoning, raw data for auditing, and a Gemini-generated performance summary for each student.
    -   `marking_form/<exam_prefix>/marked/scripts/score_report.xlsx`: A concise, marks-only sheet with student ID, Name, Class, and Total Marks.

-   **Scored Student Scripts (PDFs)**:
    -   `marking_form/<exam_prefix>/marked/pdfs/<ID>.pdf`: An individually scored script for each student, with marks annotated on the pages.
    -   `marking_form/<exam_prefix>/marked/scripts/all.pdf`: A combined PDF containing all the scored student scripts.
    -   `marking_form/<exam_prefix>/marked/scripts/sampleOf*.pdf`: Curated samples of good, average, and weak work.

-   **Archives**:
    -   `marking_form/<exam_prefix>.zip`: A zipped archive of the grading website for archival or sharing.
    -   `marking_form/<exam_prefix>/marked/scripts.zip`: A zipped archive of the `marked/scripts` folder, containing all generated PDFs and Excel reports.

-   **Intermediate Data**:
    -   `marking_form/<exam_prefix>/questions/`: Contains the per-question data (`data.csv`, `mark.json`) and the web UI files.
    -   `cache/`: Caches Gemini API calls to avoid redundant processing and costs on subsequent runs.
