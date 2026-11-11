# Colab Brain Server for StudyAssist

This folder provides `brain_server.ipynb`, a ready-to-run Google Colab notebook that hosts Ollama with Qwen 2.5 7B on Google Colab's free GPU instances and connects securely to your local StudyAssist instance.

## Important Colab ToS Notice
> Running tunnel proxies on free-tier Google Colab is subject to Google's Terms of Service and session inactivity timeouts. Use this notebook responsibly for your own personal study sessions.

## Setup Instructions
1. Open [Google Colab](https://colab.research.google.com/) and upload `colab/brain_server.ipynb`.
2. Ensure hardware accelerator is set to GPU (**Runtime** > **Change runtime type** > **T4 GPU**).
3. Run all cells in sequence (**Runtime** > **Run all**).
4. Copy the generated **Base URL** (e.g. `https://xxxx.trycloudflare.com`) and **Bearer Token**.
5. In StudyAssist UI under the **Brain & Settings** tab:
   - Select active profile `colab_ollama`.
   - Paste the Base URL and Bearer Token.
   - Click **Save Profile Settings** and **Test Brain Connection**.
