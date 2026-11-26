PromptVideo Studio — Google Cloud Veo version
This Streamlit app creates a 20–30 second MP4 by generating multiple 8-second clips with Veo through Google Cloud Gemini Enterprise Agent Platform / Vertex AI, then joining them with FFmpeg.
Important authentication change
A standard Google AI Studio Gemini API key cannot authenticate the Veo workflow used here. The app now requires:
- Google Cloud Project ID
- Google Cloud Storage bucket name
- Google Cloud service-account JSON key
- Optional Groq API key for scene planning
Google Cloud setup
1. Create or select a Google Cloud project.
2. Enable the Vertex AI API.
3. Create a Cloud Storage bucket in the project.
4. Create a service account.
5. Grant it the Vertex AI User role.
6. Grant it permission to create/read objects in the output bucket (for example, Storage Object Admin on that bucket).
7. Create a JSON key for that service account and paste its full contents into the app sidebar.
8. Enter the project ID and bucket name in the app.
Keep the service-account JSON private. Never commit it to GitHub.
Deploy
Upload app_fixed.py as app.py (rename it to app.py) and requirements_fixed.txt as requirements.txt (rename it to requirements.txt), plus this README, to your GitHub repository. In Streamlit Community Cloud select app.py.
Features and limitations
- 20, 24 or 30 second final MP4
- Landscape or portrait
- 1080p source request; 2K option upscales the 1080p output
- Groq is optional and only creates scene prompts
- Clips are generated independently; perfect continuity is not guaranteed
- Veo calls incur Google Cloud charges and require model access/quota
- Streamlit Cloud may time out during long generations; production use may need a background worker
