# BotGeorge

A Discord bot implemented in Python using [discord.py](https://discordpy.readthedocs.io/).  
The project demonstrates the integration of external APIs, media handling, and dynamic user interaction.

---

## Features

The bot supports multiple commands for entertainment and interaction:

| Command           | Description                                            |
|-------------------|--------------------------------------------------------|
| `$hello`          | Replies with a greeting                                |
| `$name`           | Introduces the bot                                     |
| `$CreateQR`       | Generates a QR code from user input                    |
| `$Meme`           | Retrieves and displays a random meme from Reddit       |
| `$Mp3 <link>`     | Extracts the audio (MP3) from a given YouTube link     |
| `$prompt`         | Provides a random art prompt                           |
| `$compliment`     | Sends a compliment                                     |
| `$fuckyou`        | Sends an offensive response (for testing purposes)     |
| `$addCompliment`  | Allows users to add new compliments                    |
| `$addRandom`      | Allows users to add random phrases                     |
| `$addSwear`       | Allows users to add new swear words                    |
| `$addPrompt`      | Allows users to add new art prompts                    |

---

### 2. Installation
Make sure Python 3.10+ is installed. Then install the required packages:

```bash
pip install -r requirements.txt

``` 

Then rename the file example_token.json to token.json in the data folder and put you discord token into the designated place.

After that you can start the bot by executing the George.py script.

---

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/BotGeorge.git
cd BotGeorge
```

### 2. Install dependencies
Make sure you have **Python 3.10+** installed. Then install all required packages:

```bash
pip install -r requirements.txt
```

### 3. Configure the bot
Create your configuration file:

1. Copy the provided template `data/exampleToken.json` and rename it to `token.json` inside the same folder.  
2. Open `token.json` and insert your [Discord Bot Token](https://discord.com/developers/applications).

### 4. Run the bot
Start the bot with:
```bash
python George.py
```

---

## Security Notice
The file `config/token.json` is excluded via `.gitignore` and must never be committed.  
For reference, the repository provides `data/exampleToken.json` as a template.

---

## Technologies Used
- **Python 3.10+**
- **discord.py** – Discord API wrapper  
- **segno** – QR code generation  
- **yt-dlp** – YouTube video/audio handling  
- **requests** – HTTP requests  

---

## License
This project is distributed under the MIT License.
