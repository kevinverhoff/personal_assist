_MODEL = "gemini-flash-lite-latest"

_PROMPT_INSTRUCTIONS = (
    "This is an email that has been tagged as unimportant and has been "
    "auto-archived. Pull out the information that the recipient needs to "
    "know from this email. Keep the summary to under 50 words, but if "
    "there are any important links (eg: to news articles or to something "
    "of interest) include them. You need to give the recipient the key "
    "information so the they don't miss anything."
)


def summarize_for_archive(client, subject: str, body: str) -> str:
    try:
        prompt = f"{_PROMPT_INSTRUCTIONS}\n\nSubject: {subject}\n\n{body[:4000]}"
        response = client.models.generate_content(model=_MODEL, contents=prompt)
        return response.text.strip()
    except Exception:
        return "Summary unavailable."
