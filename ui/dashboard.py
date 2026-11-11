"""Gradio User Interface layout, tabs, callbacks, and local server integration."""

from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import gradio as gr

from agent.dispatcher import dispatch_tool
from agent.jury import execute_jury_debate
from agent.orchestrator import run_agent
from auth.context import UserContext
from auth.database import reset_password_with_recovery_key
from auth.hasher import check_password_strength, validate_username
from auth.keyring_service import get_user_secret, set_user_secret
from auth.service import (
    change_account_password,
    delete_account,
    login_account,
    logout_account,
    register_account,
)
from config.loader import (
    get_active_profile,
    load_providers_config,
    load_settings_config,
    save_providers_config,
)
from models.hardware import run_hardware_preflight
from storage.db import (
    get_action_logs,
    get_revision_plans,
    get_weak_topics,
    is_subject_local_only,
    list_subjects,
    set_subject_local_only,
)
from storage.memory import (
    list_user_memory_subjects,
    load_subject_memory,
    update_learning_order,
)
from tools.generate_quiz import generate_quiz, grade_quiz_answers
from tools.ingest_material import ingest_material
from tools.schedule_revision import schedule_revision
from tools.search_notes import search_notes
from tools.track_progress import track_progress

INIT_THEME_JS = """
() => {
    let saved = localStorage.getItem('studyassist_theme');
    if (!saved) {
        saved = 'light';
        localStorage.setItem('studyassist_theme', 'light');
    }
    if (saved === 'dark') {
        document.body.classList.add('dark');
        document.documentElement.classList.add('dark');
    } else {
        document.body.classList.remove('dark');
        document.documentElement.classList.remove('dark');
    }
    const url = new URL(window.location);
    if (url.searchParams.get('__theme') !== saved) {
        url.searchParams.set('__theme', saved);
        window.history.replaceState({}, '', url);
    }
}
"""

TOGGLE_THEME_JS = """
() => {
    let current = localStorage.getItem('studyassist_theme') || 'light';
    let nextTheme = (current === 'dark') ? 'light' : 'dark';
    localStorage.setItem('studyassist_theme', nextTheme);

    if (nextTheme === 'dark') {
        document.body.classList.add('dark');
        document.documentElement.classList.add('dark');
    } else {
        document.body.classList.remove('dark');
        document.documentElement.classList.remove('dark');
    }

    const url = new URL(window.location);
    url.searchParams.set('__theme', nextTheme);
    window.history.replaceState({}, '', url);
}
"""


def create_app() -> gr.Blocks:
    """Build the complete StudyAssist Gradio application interface."""

    # Custom styling
    custom_css = """
    .gradio-container { max-width: 1200px !important; margin: 0 auto !important; }
    .status-badge { font-weight: bold; padding: 4px 8px; border-radius: 4px; display: inline-block; }
    .status-good { background-color: #d4edda; color: #155724; }
    .status-warn { background-color: #fff3cd; color: #856404; }
    .status-bad { background-color: #f8d7da; color: #721c24; }
    """

    with gr.Blocks(title="StudyAssist — Agentic AI Study Assistant") as demo:
        # User session state stored within Gradio session
        session_token_state = gr.State(value=None)
        user_context_state = gr.State(value=None)
        active_quiz_data_state = gr.State(value={})

        # ==================== AUTH CONTAINER ====================
        with gr.Column(visible=True) as auth_container:
            with gr.Row():
                with gr.Column(scale=9):
                    gr.Markdown("# 🎓 Welcome to **StudyAssist**")
                    gr.Markdown("Your private, offline-first study companion. Accounts keep each family member's files strictly separated.")
                with gr.Column(scale=3):
                    auth_theme_btn = gr.Button("🌓 Light / Dark", size="sm", variant="secondary")

            with gr.Tabs():
                # --- LOGIN TAB ---
                with gr.Tab("Log In"):
                    with gr.Row():
                        with gr.Column(scale=1):
                            login_user_in = gr.Textbox(label="Username", placeholder="e.g. Alex", max_lines=1)
                            login_pass_in = gr.Textbox(label="Password", type="password", placeholder="Enter your password", max_lines=1)
                            login_btn = gr.Button("Log In", variant="primary")
                            login_msg = gr.Markdown()

                # --- REGISTER TAB ---
                with gr.Tab("Create User"):
                    with gr.Row():
                        with gr.Column(scale=1):
                            reg_user_in = gr.Textbox(label="Username", placeholder="3 to 32 characters (letters, numbers, _ -)")
                            reg_pass_in = gr.Textbox(label="Password", type="password", placeholder="At least 10 characters")
                            reg_pass_hint = gr.Markdown("Password must be at least 10 characters long.")
                            reg_confirm_in = gr.Textbox(label="Confirm Password", type="password")
                            reg_btn = gr.Button("Create Account", variant="primary")
                            reg_msg = gr.Markdown()

                            # Recovery key display area
                            with gr.Group(visible=False) as recovery_group:
                                gr.Markdown("### ⚠️ Save Your One-Time Recovery Key Now!")
                                gr.Markdown("If you forget your password, this recovery key is the ONLY way to regain access to your account.")
                                rec_key_disp = gr.Textbox(label="One-Time Recovery Key", interactive=False)
                                rec_confirm_cb = gr.Checkbox(label="I have safely copied and saved this recovery key.")
                                rec_done_btn = gr.Button("Proceed to Login", variant="secondary")

                # --- ACCOUNT RECOVERY TAB ---
                with gr.Tab("Account Recovery"):
                    with gr.Row():
                        with gr.Column(scale=1):
                            recov_user_in = gr.Textbox(label="Username")
                            recov_key_in = gr.Textbox(label="Recovery Key", placeholder="STUDY-XXXX-XXXX-XXXX-XXXX")
                            recov_newpass_in = gr.Textbox(label="New Password", type="password")
                            recov_btn = gr.Button("Reset Password", variant="secondary")
                            recov_msg = gr.Markdown()

        # ==================== MAIN DASHBOARD CONTAINER ====================
        with gr.Column(visible=False) as dashboard_container:
            # Top Banner
            with gr.Row():
                with gr.Column(scale=8):
                    user_header = gr.Markdown("## Welcome back!")
                    brain_badge = gr.Markdown("🟢 Active Brain: `local_ollama` (Qwen 2.5 7B) | Local Mode")
                with gr.Column(scale=4):
                    with gr.Row():
                        dash_theme_btn = gr.Button("🌓 Theme", size="sm", variant="secondary")
                        logout_btn = gr.Button("Log Out", size="sm", variant="stop")

            with gr.Tabs() as main_tabs:
                # ----------------- TAB 1: CHAT & GOALS -----------------
                with gr.Tab("💬 Chat"):
                    with gr.Row():
                        with gr.Column(scale=8):
                            chat_history = gr.Chatbot(label="Conversation", height=450)
                        with gr.Column(scale=4):
                            chat_subject_sel = gr.Dropdown(label="Subject", choices=["General"], value="General", interactive=True)
                            chat_mode_radio = gr.Radio(label="Answering Mode", choices=["Quick (Single Agent)", "Jury (6 Agents Debate)"], value="Quick (Single Agent)")
                            cost_warning_box = gr.Markdown("💡 *Tip: Quick mode answers instantly. Jury mode runs a 6-agent peer-reviewed debate.*", visible=True)
                            citation_box = gr.Markdown("### 📚 Source Citations\n*Citations from your indexed materials will appear here.*")

                    with gr.Row():
                        chat_input = gr.Textbox(label="Your Goal or Question", placeholder="e.g. 'Exam in 10 days, make a plan' or 'Explain Newton's third law'", lines=2, scale=10)
                        chat_submit_btn = gr.Button("Submit", variant="primary", scale=2)

                # ----------------- TAB 2: UPLOAD & SUBJECTS -----------------
                with gr.Tab("📁 Upload & Subjects"):
                    with gr.Row():
                        with gr.Column(scale=5):
                            upload_subj_in = gr.Textbox(label="Subject Name", placeholder="e.g. Physics, Biology, History")
                            local_only_cb = gr.Checkbox(label="🔒 Local Only (Forbid sending any excerpts to remote cloud brains)", value=False)
                            file_upload = gr.File(label="Upload Lecture Notes / Slides / Sheets / Scans", file_types=[".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".png", ".jpg", ".jpeg"])
                            ingest_btn = gr.Button("Ingest Material", variant="primary")
                            ingest_status = gr.Markdown()

                        with gr.Column(scale=7):
                            gr.Markdown("### 📖 Subject Memory & Learning Sequence")
                            memory_subject_sel = gr.Dropdown(label="Select Subject", choices=[], interactive=True)
                            refresh_memory_btn = gr.Button("Refresh Subject List", size="sm")
                            learning_order_disp = gr.TextArea(label="Sequenced Learning Order (Computed by Code)", lines=6, interactive=True)
                            save_order_btn = gr.Button("Save Manual Order Override", size="sm")
                            order_save_msg = gr.Markdown()
                            memory_summary_disp = gr.Markdown()

                # ----------------- TAB 3: PROGRESS & QUIZZES -----------------
                with gr.Tab("📊 Progress & Quizzes"):
                    with gr.Row():
                        with gr.Column(scale=6):
                            gr.Markdown("### 🎯 Weak Topics Analysis")
                            weak_topics_disp = gr.Markdown("Take quizzes to see topic mastery statistics.")
                            refresh_progress_btn = gr.Button("Refresh Mastery Stats", size="sm")

                            gr.Markdown("### 📅 Active Spaced-Repetition Revision Plans")
                            plans_disp = gr.Markdown()

                        with gr.Column(scale=6):
                            gr.Markdown("### 📝 Grounded Quiz Evaluator")
                            quiz_subj_in = gr.Textbox(label="Subject", placeholder="e.g. Physics")
                            quiz_topic_in = gr.Textbox(label="Topic", placeholder="e.g. Kinematics")
                            generate_quiz_btn = gr.Button("Generate Grounded Quiz", variant="primary")
                            quiz_disp = gr.Markdown()

                            # Answer submission
                            quiz_ans_in = gr.Textbox(label="Your Answer (e.g. 'A' for Q1)", placeholder="A")
                            submit_quiz_ans_btn = gr.Button("Grade Answer", variant="secondary")
                            quiz_eval_disp = gr.Markdown()

                # ----------------- TAB 4: APPROVALS -----------------
                with gr.Tab("🛡️ Approvals"):
                    gr.Markdown("### ✋ Human-In-The-Loop Confirmation Gate")
                    gr.Markdown("Sensitive actions (such as generating revision schedules or exporting calendar events) pause here for your explicit approval before executing.")

                    with gr.Group():
                        approval_info = gr.Markdown("🟢 No actions currently pending approval.")
                        with gr.Row():
                            approve_btn = gr.Button("Approve Action", variant="primary", interactive=False)
                            reject_btn = gr.Button("Reject Action", variant="stop", interactive=False)
                        approval_result_disp = gr.Markdown()

                # ----------------- TAB 5: BRAIN & SETTINGS -----------------
                with gr.Tab("⚙️ Brain & Settings"):
                    with gr.Row():
                        with gr.Column(scale=6):
                            gr.Markdown("### 🧠 Brain Profile Configuration")
                            providers_cfg = load_providers_config()
                            profile_choices = list(providers_cfg.get("profiles", {}).keys())
                            active_prof = providers_cfg.get("active_profile", "local_ollama")

                            profile_dropdown = gr.Dropdown(label="Active Brain Profile", choices=profile_choices, value=active_prof)
                            model_name_in = gr.Textbox(label="Model Name (Editable, Never Hard-coded)", value=providers_cfg.get("profiles", {}).get(active_prof, {}).get("model", "qwen2.5:7b"))
                            base_url_in = gr.Textbox(label="Base URL", value=providers_cfg.get("profiles", {}).get(active_prof, {}).get("base_url", "http://localhost:11434"))
                            api_key_in = gr.Textbox(label="API Key / Colab Token (Stored in OS Keyring)", type="password", placeholder="Enter key to update keyring")
                            save_settings_btn = gr.Button("Save Profile Settings", variant="primary")
                            test_conn_btn = gr.Button("Test Brain Connection", variant="secondary")
                            settings_msg = gr.Markdown()

                        with gr.Column(scale=6):
                            gr.Markdown("### 💻 Local Hardware Diagnostics")
                            gr.Markdown("Analyzes your RAM, detects dedicated vs integrated GPUs, and runs token benchmarks.")
                            preflight_btn = gr.Button("Run Hardware Preflight Check", variant="secondary")
                            preflight_disp = gr.Markdown("*Click above to run hardware diagnostics.*")

                            gr.Markdown("---")
                            gr.Markdown("### 👤 Account Management")
                            curr_pw_in = gr.Textbox(label="Current Password", type="password")
                            new_pw_in = gr.Textbox(label="New Password", type="password")
                            confirm_new_pw_in = gr.Textbox(label="Confirm New Password", type="password")
                            chg_pw_btn = gr.Button("Change Password", size="sm")
                            chg_pw_msg = gr.Markdown()

                            del_pw_in = gr.Textbox(label="Enter Password to Confirm Deletion", type="password")
                            del_acct_btn = gr.Button("Permanently Delete Account", variant="stop", size="sm")
                            del_acct_msg = gr.Markdown()

                # ----------------- TAB 6: ACTION LOG -----------------
                with gr.Tab("📜 Action Log"):
                    gr.Markdown("### 📋 Audit Action Log")
                    gr.Markdown("Real-time audit log of every brain call, duration, token metrics, tool executions, and approval decisions. Stored locally in SQLite; never logs API keys or full file contents.")
                    refresh_log_btn = gr.Button("Refresh Log", size="sm")
                    action_log_table = gr.Dataframe(
                        headers=["Time", "Profile", "Tool", "Duration (s)", "Tokens", "Approval", "Result Excerpt"],
                        interactive=False,
                    )

        # ==================== EVENT HANDLERS ====================

        # Password live hint
        def on_pass_change(pw: str) -> str:
            ok, msg = check_password_strength(pw)
            return f"💡 {msg}"
        reg_pass_in.change(on_pass_change, inputs=[reg_pass_in], outputs=[reg_pass_hint])

        # Login event
        def do_login(username: str, password: str):
            success, msg, token, context = login_account(username, password)
            if not success or not context:
                return None, None, gr.update(value=f"❌ {msg}"), gr.update(visible=True), gr.update(visible=False), "", ""
            
            # Update user header and brain status
            welcome_text = f"## Welcome back, **{context.display_name or context.username}**!"
            active_info = get_active_profile()
            badge_text = f"🟢 Active Brain: `{active_info['name']}` ({active_info.get('model')}) | {'Local' if active_info.get('is_local') else 'Remote Cloud'}"
            
            # Load user subjects
            subjs = [s["name"] for s in list_subjects(context)]
            subj_choices = subjs if subjs else ["General"]

            return (
                token,
                context,
                gr.update(value=""),
                gr.update(visible=False),  # hide auth
                gr.update(visible=True),   # show dashboard
                welcome_text,
                badge_text,
            )

        login_btn.click(
            do_login,
            inputs=[login_user_in, login_pass_in],
            outputs=[session_token_state, user_context_state, login_msg, auth_container, dashboard_container, user_header, brain_badge]
        )

        # Register event
        def do_register(username: str, password: str, confirm: str):
            success, msg, rec_key = register_account(username, password, confirm)
            if not success:
                return gr.update(value=f"❌ {msg}"), gr.update(visible=False), ""
            return (
                gr.update(value="✅ Account registered! Save your recovery key below to finish:"),
                gr.update(visible=True),
                rec_key or "",
            )

        reg_btn.click(
            do_register,
            inputs=[reg_user_in, reg_pass_in, reg_confirm_in],
            outputs=[reg_msg, recovery_group, rec_key_disp]
        )

        # Recovery proceed to login
        rec_done_btn.click(
            lambda: (gr.update(visible=False), gr.update(value="")),
            inputs=[],
            outputs=[recovery_group, reg_msg]
        )

        # Reset password via recovery key
        def do_recovery(username: str, key: str, new_pw: str):
            success, msg = reset_password_with_recovery_key(username, key, new_pw)
            if success:
                return f"✅ {msg} You may now log in with your new password."
            return f"❌ {msg}"

        recov_btn.click(
            do_recovery,
            inputs=[recov_user_in, recov_key_in, recov_newpass_in],
            outputs=[recov_msg]
        )

        # Logout event
        def do_logout(token: Optional[str]):
            logout_account(token)
            return None, None, gr.update(visible=True), gr.update(visible=False)

        logout_btn.click(
            do_logout,
            inputs=[session_token_state],
            outputs=[session_token_state, user_context_state, auth_container, dashboard_container]
        )

        # Ingest file event
        def do_ingest(file_obj, subject: str, local_only: bool, context: Optional[UserContext]):
            if not context:
                return "❌ Error: Session expired. Please log in again."
            if not file_obj or not subject:
                return "❌ Please specify a subject name and select a file to upload."

            set_subject_local_only(context, subject, local_only)
            file_path = file_obj.name if hasattr(file_obj, "name") else str(file_obj)
            res = ingest_material(file_path=file_path, subject=subject, user_context=context)
            return res

        ingest_btn.click(
            do_ingest,
            inputs=[file_upload, upload_subj_in, local_only_cb, user_context_state],
            outputs=[ingest_status]
        )

        # Refresh memory subject list
        def do_refresh_memory(context: Optional[UserContext]):
            if not context:
                return gr.update(choices=[]), "", ""
            subjs = list_user_memory_subjects(context)
            return gr.update(choices=subjs, value=subjs[0] if subjs else None), "", ""

        refresh_memory_btn.click(
            do_refresh_memory,
            inputs=[user_context_state],
            outputs=[memory_subject_sel, learning_order_disp, memory_summary_disp]
        )

        # Subject selected in memory tab
        def on_memory_subject_selected(subj: str, context: Optional[UserContext]):
            if not context or not subj:
                return "", ""
            data = load_subject_memory(context, subj)
            order = "\n".join(data.get("learning_order", []))
            summary_lines = [
                f"**Files Ingested**: {len(data.get('files', []))}",
                f"**Extracted Topics**: {len(data.get('topics', []))}",
                f"**Local Only Restricted**: {'Yes' if data.get('local_only') else 'No'}",
            ]
            return order, "\n".join(summary_lines)

        memory_subject_sel.change(
            on_memory_subject_selected,
            inputs=[memory_subject_sel, user_context_state],
            outputs=[learning_order_disp, memory_summary_disp]
        )

        # Save order override
        def do_save_order(subj: str, text: str, context: Optional[UserContext]):
            if not context or not subj:
                return "❌ Select a subject first."
            topics = [line.strip() for line in text.splitlines() if line.strip()]
            update_learning_order(context, subj, topics)
            return f"✅ Saved manual sequence with {len(topics)} topic(s)."

        save_order_btn.click(
            do_save_order,
            inputs=[memory_subject_sel, learning_order_disp, user_context_state],
            outputs=[order_save_msg]
        )

        # Chat execution event
        def do_chat(
            goal: str,
            subject: str,
            mode_choice: str,
            history: Optional[List[Dict[str, Any]]],
            context: Optional[UserContext],
        ):
            new_history: List[Dict[str, Any]] = []
            if history:
                for item in history:
                    if isinstance(item, dict):
                        new_history.append(item)
                    elif isinstance(item, (list, tuple)) and len(item) == 2:
                        new_history.append({"role": "user", "content": str(item[0])})
                        new_history.append({"role": "assistant", "content": str(item[1])})

            if not context:
                new_history.append({"role": "assistant", "content": "⚠️ Session expired. Please log in again."})
                return new_history, "", ""

            if not goal or not goal.strip():
                return new_history, "", ""

            mode = "quick" if "Quick" in mode_choice else "jury"

            # If user explicitly asks for question answer or debate
            if mode == "jury":
                debate_res = execute_jury_debate(question=goal, subject=subject, user_context=context, mode="jury")
                answer = debate_res.get("final_answer", "")
                cites = debate_res.get("citations", [])
                cite_md = "### 📚 Source Citations\n" + "\n".join([f"• {c}" for c in cites]) if cites else ""
            else:
                agent_res = run_agent(task=goal, user_context=context, options={"subject": subject}, auto_approve=False)
                answer = agent_res.get("final_answer", "")
                cite_md = "### 📚 Source Citations\n*(Quick mode response)*"

            new_history.append({"role": "user", "content": goal})
            new_history.append({"role": "assistant", "content": answer})
            return new_history, cite_md, ""

        chat_submit_btn.click(
            do_chat,
            inputs=[chat_input, chat_subject_sel, chat_mode_radio, chat_history, user_context_state],
            outputs=[chat_history, citation_box, chat_input],
        )
        chat_input.submit(
            do_chat,
            inputs=[chat_input, chat_subject_sel, chat_mode_radio, chat_history, user_context_state],
            outputs=[chat_history, citation_box, chat_input],
        )

        # Progress tab refresh
        def do_refresh_progress(context: Optional[UserContext]):
            if not context:
                return "Log in to view progress.", "No plans."
            report = track_progress(context)
            plans = get_revision_plans(context)
            plans_text = ""
            for p in plans:
                plans_text += f"• **{p['subject']}**: Exam {p['exam_date']} ({p['hours_per_day']} hrs/day) [Download ICS]({p['ics_path']})\n"
            return report, plans_text or "No revision plans created yet."

        refresh_progress_btn.click(
            do_refresh_progress,
            inputs=[user_context_state],
            outputs=[weak_topics_disp, plans_disp]
        )

        # Generate quiz
        def do_gen_quiz(subj: str, topic: str, context: Optional[UserContext]):
            if not context or not subj or not topic:
                return "❌ Please enter both a subject and a topic."
            quiz_txt = generate_quiz(subject=subj, topic=topic, user_context=context)
            return quiz_txt

        generate_quiz_btn.click(
            do_gen_quiz,
            inputs=[quiz_subj_in, quiz_topic_in, user_context_state],
            outputs=[quiz_disp]
        )

        # Grade quiz
        def do_grade_quiz(subj: str, topic: str, ans: str, context: Optional[UserContext]):
            if not context:
                return "Log in required."
            res = grade_quiz_answers(subject=subj, topic=topic, student_answers={1: ans}, user_context=context)
            if "error" in res:
                return f"❌ {res['error']}"
            feedback_str = "\n".join(res.get("feedback", []))
            return f"**Score: {res['score']}/{res['total']} ({res['percentage']}%)**\n\n{feedback_str}"

        submit_quiz_ans_btn.click(
            do_grade_quiz,
            inputs=[quiz_subj_in, quiz_topic_in, quiz_ans_in, user_context_state],
            outputs=[quiz_eval_disp]
        )

        # Hardware preflight check
        def do_preflight():
            res = run_hardware_preflight()
            lines = [
                f"### System Evaluation: **{res['verdict']}**",
                f"- **Architecture**: {res['machine_type']}",
                f"- **RAM**: {res['total_ram_gb']} GB total ({res['free_ram_gb']} GB available)",
                f"- **Ollama Active**: {'Yes' if res['ollama_reachable'] else 'No'}",
                f"- **VRAM Allocated**: {res['vram_percentage']}%",
                f"- **Generation Speed**: {res['tokens_per_second'] or 'N/A'} tokens/sec",
                f"\n**Recommendation**: {res['suggestion']}",
                f"\n> 💡 {res['vulkan_tip']}",
            ]
            return "\n\n".join(lines)

        preflight_btn.click(
            do_preflight,
            inputs=[],
            outputs=[preflight_disp]
        )

        # Test brain connection
        def do_test_connection(prof_name: str, context: Optional[UserContext]):
            from models.brain import test_brain_connection
            res = test_brain_connection(prof_name, user_context=context)
            status = res.get("status")
            msg = res.get("message", "")
            if status == "ok":
                return f"✅ **Operational**: {msg}"
            elif status == "warning":
                return f"⚠️ **Notice**: {msg}"
            return f"❌ **Error**: {msg}"

        test_conn_btn.click(
            do_test_connection,
            inputs=[profile_dropdown, user_context_state],
            outputs=[settings_msg]
        )

        # Save profile settings
        def do_save_settings(prof_name: str, base_url: str, api_key: str, context: Optional[UserContext]):
            from config.loader import load_providers_config, save_providers_config
            from auth.keyring_service import set_user_secret
            cfg = load_providers_config()
            cfg["active_profile"] = prof_name
            if prof_name in cfg.get("profiles", {}):
                cfg["profiles"][prof_name]["base_url"] = base_url
            save_providers_config(cfg)
            if api_key.strip() and context:
                secret_key = "colab_token" if "colab" in prof_name else "cloud_api_key"
                set_user_secret(context.user_id, secret_key, api_key.strip())
            return f"✅ Settings for profile '{prof_name}' saved successfully."

        save_settings_btn.click(
            do_save_settings,
            inputs=[profile_dropdown, base_url_in, api_key_in, user_context_state],
            outputs=[settings_msg]
        )

        # Action log refresh
        def do_refresh_logs(context: Optional[UserContext]):
            if not context:
                return []
            logs = get_action_logs(context, limit=50)
            rows = []
            for item in logs:
                rows.append([
                    time_str := str(date.fromtimestamp(item["created_at"])),
                    item["profile_name"],
                    item["tool_name"],
                    item["duration_sec"],
                    f"{item['prompt_tokens']} / {item['completion_tokens']}",
                    item["approval_status"],
                    item["tool_result"][:80],
                ])
            return rows

        refresh_log_btn.click(
            do_refresh_logs,
            inputs=[user_context_state],
            outputs=[action_log_table]
        )

        # Change Password
        def do_change_pw(curr: str, new: str, conf: str, context: Optional[UserContext]):
            if not context:
                return "Session expired."
            ok, msg = change_account_password(context.user_id, curr, new, conf)
            return f"✅ {msg}" if ok else f"❌ {msg}"

        chg_pw_btn.click(
            do_change_pw,
            inputs=[curr_pw_in, new_pw_in, confirm_new_pw_in, user_context_state],
            outputs=[chg_pw_msg]
        )

        # Delete Account
        def do_del_acct(pw: str, token: Optional[str], context: Optional[UserContext]):
            if not context:
                return "Session expired.", gr.update(visible=False), gr.update(visible=True)
            ok, msg = delete_account(context.user_id, pw, session_token=token)
            if ok:
                return f"✅ {msg}", gr.update(visible=True), gr.update(visible=False)
            return f"❌ {msg}", gr.update(visible=False), gr.update(visible=True)

        del_acct_btn.click(
            do_del_acct,
            inputs=[del_pw_in, session_token_state, user_context_state],
            outputs=[del_acct_msg, auth_container, dashboard_container]
        )

        # Theme switching events and initial light theme enforcement
        auth_theme_btn.click(fn=None, js=TOGGLE_THEME_JS)
        dash_theme_btn.click(fn=None, js=TOGGLE_THEME_JS)
        demo.load(fn=None, js=INIT_THEME_JS)

    return demo
