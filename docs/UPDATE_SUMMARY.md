I have updated `notebbooks/step6_scoring_postprocessing.ipynb` to include the `generate_question_insights_with_ai` functionality.

A new cell has been inserted before the Word report generation step. This cell:
1.  **Constructs the Payload:** Gathers question statistics from `metrics_df`, marking schemes, and sample high/low scoring answers for each question.
2.  **Invokes AI Agent:** Calls `generate_question_insights_with_ai` to produce a "Deep Dive" analysis report and an infographic.
3.  **Displays Results:** Prints the generated report text and the path to the infographic.
4.  **Saves to Excel:** Appends the report text and infographic path to a new "QuestionInsights" sheet in `details_score_report.xlsx`.

**Bug Fixes:** 
- Resolved an `UnboundLocalError` in the `generate_question_insights` function by ensuring consistent local variable assignment for the metrics dataframe (`metrics_df`) and correctly iterating over it.
- Fixed a `NameError` in `notebbooks/agents/analytics_agent/agent.py` by correcting the function call from `run_agent_with_retry_custom` to `run_agent_with_retry`.

The notebook is valid, tested, and ready to run.