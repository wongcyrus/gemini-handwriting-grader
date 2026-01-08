import nbformat
import re

notebook_path = "notebbooks/step6_scoring_postprocessing.ipynb"

def reorder_code(source):
    # Split into lines
    lines = source.splitlines(keepends=True)
    
    # Define block markers (using unique substrings)
    markers = {
        'start': 'def generate_word_report():',
        'gemini_narrative': '# Add Gemini narrative if available',
        'infographic': '# Add Infographic if available',
        'class_charts': '# Generate and add class-level charts',
        'metrics_table': '# Add metrics table',
        'question_metrics': '# Add per-question metrics if available',
        'question_insights': '# Add AI Question Insights',
        'strengths_focus': '# Add strengths and focus areas',
        'footer': '# Add footer with generation info'
    }
    
    # Find indices
    indices = {}
    for key, marker in markers.items():
        found = False
        for i, line in enumerate(lines):
            if marker in line:
                indices[key] = i
                found = True
                break
        if not found:
            print(f"Warning: Marker '{key}' not found.")
            return source

    # Extract blocks
    # We assume the order in the current file is:
    # start -> gemini_narrative -> infographic -> class_charts -> metrics_table -> question_metrics -> question_insights -> strengths_focus -> footer
    
    # Validate assumptions about current order based on indices
    sorted_keys = sorted(indices, key=indices.get)
    print(f"Detected block order: {sorted_keys}")
    
    # Define bounds
    # Block A (Start to Narrative): indices['start'] to indices['gemini_narrative']
    blocks = {}
    
    # Base part (includes imports, doc creation, helper func)
    blocks['base'] = lines[indices['start'] : indices['gemini_narrative']]
    
    # Gemini Narrative
    blocks['gemini_narrative'] = lines[indices['gemini_narrative'] : indices['infographic']]
    
    # Infographic
    blocks['infographic'] = lines[indices['infographic'] : indices['class_charts']]
    
    # Class Charts
    blocks['class_charts'] = lines[indices['class_charts'] : indices['metrics_table']]
    
    # Metrics Table
    blocks['metrics_table'] = lines[indices['metrics_table'] : indices['question_metrics']]
    
    # Question Metrics & Charts (This block contained the insertion point for insights in previous edits)
    # Wait, in the current file, 'question_insights' was inserted inside or after 'question_metrics' block?
    # Let's check the detected order.
    # If insights is AFTER charts exception, it's distinct.
    
    # Let's assume indices are distinct and sequential.
    
    # Sort markers by line number to define chunks dynamically
    sorted_markers = sorted(indices.items(), key=lambda x: x[1])
    
    chunks = {}
    for i in range(len(sorted_markers)):
        key, start_idx = sorted_markers[i]
        if i < len(sorted_markers) - 1:
            end_idx = sorted_markers[i+1][1]
            chunks[key] = lines[start_idx : end_idx]
        else:
            # Last block goes until end of function (or start of main call)
            # The function ends before "word_report_path = generate_word_report()"
            # We'll just grab until the end of the cell or specific marker?
            # The cell contains the function and the call.
            # Let's grab until the end of the lines provided.
            chunks[key] = lines[start_idx:]

    # Desired Order:
    # 1. Base (Title, Stats, Helper)
    # 2. Gemini Narrative
    # 3. Infographic
    # 4. Question Insights
    # 5. Strengths & Focus
    # 6. Class Charts
    # 7. Metrics Table
    # 8. Question Metrics (includes per-question table and charts)
    # 9. Footer (and Save)
    
    new_order = [
        'start',
        'gemini_narrative',
        'infographic',
        'question_insights',
        'strengths_focus',
        'class_charts',
        'metrics_table',
        'question_metrics',
        'footer'
    ]
    
    # Reassemble
    new_source_lines = []
    for key in new_order:
        if key in chunks:
            new_source_lines.extend(chunks[key])
        else:
            print(f"Error: Missing chunk for {key}")
            return source
            
    return "".join(new_source_lines)

# Process notebook
with open(notebook_path, "r", encoding="utf-8") as f:
    nb = nbformat.read(f, as_version=4)

processed = False
for cell in nb.cells:
    if cell.cell_type == "code" and "def generate_word_report():" in cell.source:
        print("Found generation cell.")
        new_source = reorder_code(cell.source)
        if new_source != cell.source:
            cell.source = new_source
            processed = True
            print("Cell reordered.")
        else:
            print("No changes made (markers missing or source identical).")
        break

if processed:
    with open(notebook_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
    print("Notebook saved.")
else:
    print("Failed to process notebook.")
