from openai import OpenAI

# Available local models
MODELS = ["qwen2.5-3b-instruct", "llama-3.2-3b-instruct"]
DEFAULT_MODEL = MODELS[0]

# Connect to LM Studio
client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="lm-studio",
    timeout=60.0
)


# Send a prompt to the selected model and return its response
def ask_model(prompt, model=DEFAULT_MODEL):
    if model not in MODELS:
        raise ValueError(f"Unknown model: {model}")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    return response.choices[0].message.content