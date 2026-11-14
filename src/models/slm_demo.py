import sys
from openai import OpenAI

# Available models
MODELS = ["qwen2.5-3b-instruct", "llama-3.2-3b-instruct"]

# Choose the model from the command line
model = sys.argv[1] if len(sys.argv) > 1 else MODELS[0]

if model not in MODELS:
    print(f"Unknown model: {model}")
    print(f"Available models: {', '.join(MODELS)}")
    sys.exit(1)

# Connect to the local LM Studio server
client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="lm-studio"
)

# Send a prompt to the selected model
response = client.chat.completions.create(
    model=model,
    messages=[
        {
            "role": "user",
            "content": "I want to visit Rome for 2 days. What should I see?"
        }
    ]
)

print(f"\nModel: {model}\n")
print(response.choices[0].message.content)