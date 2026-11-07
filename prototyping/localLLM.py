from ollama import chat

# Damit das script funktioniert muss man zuerst ollama starten.

modelName = 'gemma3:12b'
log = [] #Chatlog Array

def messageToModel(mes):
    answer = ""

    stream = chat(
        model = modelName,
        messages = [{'role': 'user', 'content': f'{mes}'}],
        stream = True,
    ) 

    for chunk in stream:
        text = chunk["message"]["content"]
        print(text.encode("cp1252", errors="replace").decode("cp1252"), end="", flush=True)
        answer = answer + text.encode("cp1252", errors="replace").decode("cp1252")
