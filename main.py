# copyright 2023 © Xron Trix | https://github.com/Xrontrix10
# Adapted for Universal Media Bot - Colab ⇄ Git connector.


# @title <font color=red> 🖥️ Universal Media Bot - Colab Connector

# @title Main Code
# @markdown <div><center><img src="https://user-images.githubusercontent.com/125879861/255391401-371f3a64-732d-4954-ac0f-4f093a6605e1.png" height=80></center></div>
# @markdown <center><h4>Read <b>The README</b> of your repo before deploying</a></h4></center>
# @markdown <br><center><h2><font color=lime><strong>Fill all Credentials, Run The Cell and Start The Bot</strong></h2></center>
# @markdown <br><br>

# @markdown ### 🔗 Your repository
REPO_URL = "https://github.com/your-username/universal-media-bot"  # @param {type: "string"}
BRANCH = "main"  # @param {type: "string"}
CLEAN_CLONE = True  # @param {type: "boolean"}

# @markdown ### 🔑 Telegram credentials
API_ID = 18443762  # @param {type: "integer"}
API_HASH = "a14eb15b00ffaa1f54a7bf93cd521e92"  # @param {type: "string"}
BOT_TOKEN = "7454146246:AAGhnsCEjuxf6tIoxxUARbr1MxmN39O_5Ns"  # @param {type: "string"}
USER_ID = 1091956543  # @param {type: "integer"}
DUMP_ID = -1002521564194  # @param {type: "integer"}

# @markdown ### 🍪 Twitter / X cookies
# @markdown Paste the JSON array (`[{"name":"auth_token","value":"..."}, ...]`) or leave empty.
TWITTER_COOKIES = "[]"  # @param {type: "string"}

# @markdown ### ⚙️ Bot behaviour
MAX_FILE_SIZE_MB = 2000  # @param {type: "integer"}
SEND_AS_ALBUM = True  # @param {type: "boolean"}
ALBUM_SIZE = 10  # @param {type: "slider", min: 1, max: 50, step: 1}
DELAY_BETWEEN_FILES = 3  # @param {type: "slider", min: 0, max: 60, step: 1}
ENABLE_CUSTOM_CAPTIONS = True  # @param {type: "boolean"}
AUTO_CLEANUP = True  # @param {type: "boolean"}
MESSAGE_DELETE_DELAY = 10  # @param {type: "integer"}
DOWNLOAD_PATH = "/content/Downloads"  # @param {type: "string"}

# @markdown ### 🧹 Session
RESET_SESSION = True  # @param {type: "boolean"}


import subprocess, time, json, shutil, os
from IPython.display import clear_output, display, HTML
from threading import Thread

WORK_DIR = "/content/universal-media-bot"
SESSION_FILE = f"{WORK_DIR}/media_bot.session"

Working = True

banner = '''

 ____   ____.______  ._______  .______       _____._.______  .___  ____   ____
 \\   \\_/   /: __   \\ : .___  \\ :      \\      \\__ _:|: __   \\ : __| \\   \\_/   /
  \\___ ___/ |  \\____|| :   |  ||       |       |  :||  \\____|| : |  \\___ ___/
  /   _   \\ |   :  \\ |     :  ||   |   |       |   ||   :  \\ |   |  /   _   \\
 /___/ \\___\\|   |___\\ \\_. ___/ |___|   |       |   ||   |___\\|   | /___/ \\___\\
            |___|       :/         |___|       |___||___|    |___|
                        :


              _____     __     __     __              __
             / ___/__  / /__ _/ /    / / ___ ___ ____/ /  ___ ____
            / /__/ _ \\/ / _ `/ _ \\  / /_/ -_) -_) __/ _ \\/ -_) __/
            \\___/\\___/_/\\_,_/_.__/ /____|__/\\__/\\__/_//_/\\__/_/



'''

print(banner)


def keep_alive(url):
    display(HTML(f'<audio src="{url}" controls autoplay style="display:none"></audio>'))


def Loading():
    white = 37
    black = 0
    while Working:
        print("\r" + "░"*white + "▒▒" + "▓"*black + "▒▒" + "░"*white, end="")
        black = (black + 2) % 75
        white = (white - 1) if white != 0 else 37
        time.sleep(2)
    clear_output()


audio_url = "https://raw.githubusercontent.com/KoboldAI/KoboldAI-Client/main/colab/silence.m4a"
audio_thread = Thread(target=keep_alive, args=(audio_url,))
audio_thread.start()
_Thread = Thread(target=Loading, name="Prepare", args=())
_Thread.start()

# Normalise a raw channel id (e.g. 2521564194 -> -1002521564194)
if len(str(DUMP_ID)) == 10 and "-100" not in str(DUMP_ID):
    n_dump = "-100" + str(DUMP_ID)
    DUMP_ID = int(n_dump)

# Parse the Twitter cookies string; tolerate empty / malformed input
try:
    cookies_parsed = json.loads(TWITTER_COOKIES) if TWITTER_COOKIES.strip() else []
except Exception as ex:
    print(f"⚠️ TWITTER_COOKIES is not valid JSON, ignoring: {ex}")
    cookies_parsed = []

if os.path.exists("/content/sample_data"):
    shutil.rmtree("/content/sample_data")

# Clone the repo (optionally a clean copy so "Run all" picks up the latest commit)
if CLEAN_CLONE and os.path.exists(WORK_DIR):
    shutil.rmtree(WORK_DIR)

if not os.path.exists(WORK_DIR):
    cmd = f"git clone --branch {BRANCH} {REPO_URL} {WORK_DIR}"
    proc = subprocess.run(cmd, shell=True)
else:
    cmd = f"cd {WORK_DIR} && git fetch --all && git reset --hard origin/{BRANCH}"
    proc = subprocess.run(cmd, shell=True)

cmd = "apt update && apt install -y ffmpeg megatools"
proc = subprocess.run(cmd, shell=True)

cmd = f"pip3 install -r {WORK_DIR}/requirements.txt"
proc = subprocess.run(cmd, shell=True)

# Write credentials.json in the schema the media_bot package expects
credentials = {
    "API_ID": API_ID,
    "API_HASH": API_HASH,
    "BOT_TOKEN": BOT_TOKEN,
    "OWNER": USER_ID,
    "DUMP_CHANNEL_ID": DUMP_ID,

    "MAX_FILE_SIZE_MB": MAX_FILE_SIZE_MB,
    "SEND_AS_ALBUM": SEND_AS_ALBUM,
    "ALBUM_SIZE": ALBUM_SIZE,
    "DELAY_BETWEEN_FILES": DELAY_BETWEEN_FILES,
    "ENABLE_CUSTOM_CAPTIONS": ENABLE_CUSTOM_CAPTIONS,
    "AUTO_CLEANUP": AUTO_CLEANUP,
    "MESSAGE_DELETE_DELAY": MESSAGE_DELETE_DELAY,
    "DOWNLOAD_PATH": DOWNLOAD_PATH,
    "TWITTER_COOKIES": cookies_parsed,
}

with open(f"{WORK_DIR}/credentials.json", "w") as file:
    file.write(json.dumps(credentials, indent=4))

Working = False

if RESET_SESSION and os.path.exists(SESSION_FILE):
    os.remove(SESSION_FILE)  # Remove previous bot session
    print("🧹 Previous session removed")

print("\n⚙️  Effective settings:")
print(f"   • Max file size   : {MAX_FILE_SIZE_MB} MB")
print(f"   • Album mode      : {'on' if SEND_AS_ALBUM else 'off'} (size {ALBUM_SIZE})")
print(f"   • Custom captions : {'on' if ENABLE_CUSTOM_CAPTIONS else 'off'}")
print(f"   • Auto cleanup    : {'on' if AUTO_CLEANUP else 'off'}")
print(f"   • Delay between   : {DELAY_BETWEEN_FILES}s")
print(f"   • Message delete  : {MESSAGE_DELETE_DELAY}s")
print(f"   • Downloads to    : {DOWNLOAD_PATH}")
print(f"   • Twitter cookies : {'present' if cookies_parsed else 'none'}")

print("\rStarting Bot....")

!cd /content/universal-media-bot/ && python3 -m media_bot #type:ignore
