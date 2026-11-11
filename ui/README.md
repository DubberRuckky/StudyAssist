# User Interface (`ui/`)

This directory contains the local Gradio web interface.

## Safety & Binding
The interface binds strictly to `127.0.0.1` and explicitly prohibits public sharing links (`share=False`). No outside network entity can access the application.

## UI Components & Tabs
- `auth_view.py`: Login screen, password validation, user registration with strength check, and one-time recovery key display.
- `app.py`: Main dashboard displaying:
  - **Chat**: Conversation interface supporting quick mode and jury mode toggling, showing citation references.
  - **Upload & Subjects**: File uploader (PDF, DOCX, PPTX, XLSX, images), topic order viewer, and per-subject "Local Only" brain switch.
  - **Progress**: Mastery statistics, weak topics list, and revision plan overview.
  - **Approvals**: Human-in-the-loop confirmation modal for sensitive tools such as `schedule_revision`.
  - **Brain & Settings**: Active brain indicator, fallback list, API key inputs (stored in OS keyring), connection test, and hardware check summary.
  - **Action Log**: Real-time audit log of tool calls, arguments, timings, and token metrics.
  - **Account Management**: Password change and account deletion.

## What to Edit
- To modify visual layout or theme elements, edit `ui/app.py` or `ui/auth_view.py`.
