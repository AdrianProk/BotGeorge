import discord
import json
import random
import segno
import os

from requestTest import download_random_media
from youtube import toMp3

intents = discord.Intents.default()
intents.messages = True  
intents.message_content = True

client = discord.Client(intents=intents)

#subreddits:

subs = ["Animemes","anime_irl","hopeposting","meme","me_irl","girlsfrontline","GFLNeuralCloud","FunnyAnimals"]

#--------------------------------------------------------------
#ToDo:
#die Meme funktion gibt nur video's ohne ton aus. das muss gefixt werden.
#die PDF funktion einbauen.
#die MP3 funktion fügt noch kein Album picture hinzu.
#--------------------------------------------------------------

def get_prompt():
    prompt = read_from_json_random("Art prompts")
    return prompt

def get_swear():
    swear = read_from_json_random("Swears")
    return swear

def get_compliment():
    compliment= read_from_json_random("complement")
    return compliment

def get_random():
    rad = read_from_json_random("Random")
    return rad

def get_help():
    #Step 1: seek psychiatrist
    help = read_from_json("help")
    ret = ""
    for x in range(len(help)):
        ret = ret + help[x]
    return ret

#----------------------------------------------------------

def read_from_json(list_name):
    try: 
        with open("Data.json",'r') as file:
            coollist = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print("File Not Found")
    
    if list_name in coollist:
        return coollist[list_name]
    else:
        print("List not in json")

def read_from_json_random(list_name):
    try:
        with open("Data.json",'r') as file:
            coollist = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print("File Not Found")
    
    if list_name in coollist:
        return random.choice(coollist[list_name])

def write_to_json(data,list_name):
    try:
        with open("Data.json", 'r') as file:
            coollist = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        coollist = {
            "Art prompts": [],
            "Swears": [],
            "complement": [],
            "Random": []
        }
    
    if list_name in coollist:
        coollist[list_name].append(data)
    else:
        print("Error: no such list in json")
        return
    
    with open("Data.json", 'w') as file:
        json.dump(coollist, file, indent=4)
        print(f"{data} was added to list {list_name}")


def generateQR(input):
    slts_qrcode = segno.make_qr(input)
    slts_qrcode.save(  
        "qr.png",
        scale=10,
    )

#findes a filename with uncleare ending
def find_file(filename, dir="."):
    for datei in os.listdir(dir):
        if datei.startswith(filename):
            print(f"File found: {datei}")
            return datei 
    
    print("File not found.")
    return None

#delites the previes downloaded file to not overuse storage
def del_file(file):
    try:
        os.remove(file)
        print(f"{file} was removed")
    except FileNotFoundError:
        print(f"{file} not found :(")
#----------------------------------------------------------------
# this takes the given message and calls the corosponding funktions

@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')


# Resposes 
@client.event
async def on_message(message):
    if message.author == client.user:
        return

    #the standard
    if message.content.startswith('$hello'):
        await message.channel.send('Hello!') 

    if message.content.startswith('$name'):
        await message.channel.send('My name is George, the creapy Gargoyle :D') 


    #the add's
    if message.content.startswith('$addPrompt'):
        prompt_text = message.content[len('$addPrompt '):]

        if prompt_text.strip():
            write_to_json(prompt_text,"Art prompts")
            await message.channel.send(f'Your Prompt has bin Saved :D')
        else:
            await message.channel.send("What's your prompt? it cant be empty. please type your prompt after $addPrompt. All in the same Line :)")

    if message.content.startswith('$addSwear'):
        prompt_text = message.content[len('$addSwear '):]

        if prompt_text.strip():
            write_to_json(prompt_text,"Swears")
            await message.channel.send(f'Now i learned something bad >:D')
        else:
            await message.channel.send("Thas it?!?!? You have to say something if you want me to learn some thing bad! please write something behind $addSwear")


    if message.content.startswith('$addCompliment'):
        prompt_text = message.content[len('$addCompliment '):]

        if prompt_text.strip():
            write_to_json(prompt_text,"complement")
            await message.channel.send(f'Now i learned something nice :D')
        else:
            await message.channel.send("You have to say something to teach me something nice. Please write your compliment after $addComplement")

    if message.content.startswith('$addRandom'):
        prompt_text = message.content[len('$addRandom '):]

        if prompt_text.strip():
            write_to_json(prompt_text,"Random")
            await message.channel.send(f'Now i learned something Random :D')
        else:
            await message.channel.send("You have to say something to teach me something. Please write something after $addRandom")


    #the gets()----------------------------------------------------------------------

    if message.content.startswith('$fuckyou'):
        await message.channel.send(get_swear())

    if message.content.startswith('$prompt'):
        await message.channel.send(get_prompt())

    if message.content.startswith('$compliment'):
        await message.channel.send(get_compliment())

    if message.content.startswith('$random'):
        await message.channel.send(get_random())

    # Funktionality-------------------------------------------------------------------------------

    # posting memes
    if message.content.startswith('$Meme'):
        sub = random.choice(subs)
        download_random_media(sub) #downloads a random post from a given subreddit 
        fille = find_file("leMeme", "./media")
        await message.channel.send(f"Hier is a meme, just for you :) i got if from r/{sub}", file =discord.File(f"./media/{fille}"))
        del_file(f"./media/{fille}")

    # QR code creation
    if message.content.startswith('$CreateQR'):
        prompt_text = message.content[len('$CreateQR '):]

        if prompt_text.strip():
            generateQR(prompt_text)
            await message.channel.send("Hier is your QR code :)", file=discord.File('./qr.png'))
        else:
            await message.channel.send("Please put something behind $CreateQR or else i can't put something in it")

    # MP3 Converter
    if message.content.startswith('$Mp3'):
        prompt_text = message.content[len('$Mp3 '):]

        if(message.content.startswith('$Mp3 https://www.youtube.com/watch?v')):
            await message.channel.send("Alright, give me a moment...... ")
            filename = toMp3(prompt_text)
            filename = './'+filename
            try:
                await message.channel.send("Hier is your Mp3 :)",file=discord.File(filename))
            except:
                await message.channel.send("I think your Mp3 fiel was to big for Discord :(")
            os.remove(filename)
        else:
            await message.channel.send("Please put a valid Youtube link behind $Mp3")

    #help message
    if message.content.startswith('$help'):
        help = get_help()
        await message.channel.send(help)

client.run('Mzk2NzMyMzM2OTQwNjQ2NDEw.G-vg5S.hMy-Q1Tijogz7nLuk6hjaClpQIzj1-16e7dlO8')  
