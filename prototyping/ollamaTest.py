import os
from ollama import chat
from datetime import datetime
import pandas as pd

# Damit das script funktioniert muss man zuerst ollama starten.


modelName = 'gemma3:12b'
log = [] #Chatlog Array

df = pd.DataFrame(log)
df.to_csv("chatlog.csv", index=False, encoding="utf-8")

def messageToModel(mes):
    answer = ""

    stream = chat(
        model = modelName,
        messages = [{'role': 'user', 'content': f'{mes}'}],
        stream = True,
    ) 

    log.append({
        "time": datetime.now().isoformat(timespec="seconds"),
        "role": "user",
        "content": mes
    })

    for chunk in stream:
        text = chunk["message"]["content"]
        print(text.encode("cp1252", errors="replace").decode("cp1252"), end="", flush=True)
        answer = answer + text.encode("cp1252", errors="replace").decode("cp1252")
    
    log.append({
        "time": datetime.now().isoformat(timespec="seconds"),
        "role": "model",
        "content": answer
    })

def printApend():
    print(log)

def logToCSV(entry, filename="chatlog.csv"):
    try:
        df = pd.DataFrame([entry])
        df.to_csv(filename, mode="a", header=not os.path.exists(filename), index = False, encoding="utf-8") 
    except:
        print("Something wrong in CSV writing")

def logChat():
    for x in log:
        logToCSV(x)

def main():
    print("1. aussage")
    messageToModel('Hallo')

    print("2. aussage")
    messageToModel('Sag nix auser "was cooles"')
    print("\n")
    print("===================")
    printApend()
    print("\n")
    print("===================")
    print("log to cvs file\n")
    logChat()
    print("Done")
    

if __name__ == "__main__":
    main()
