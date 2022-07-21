import requests, re, time, codecs
from fastapi import FastAPI, Form, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, Response, HTMLResponse
#from jsmin import jsmin
from bs4 import BeautifulSoup

# time stuff
from datetime import datetime
import pytz

def get_int(string):
    return int(re.search(r'(\d+)', string).group(1))

jst = pytz.timezone("Asia/Tokyo") # used for time conversion
magic = codecs.decode("nvzrVq","rot-13") # hi sega

class DifficultyStats:
    def __init__(self, score, rate, achieve, play_count):
        self.score = score
        self.rate = rate
        self.achieve = achieve
        self.play_count = play_count

    def __str__(self):
        return self.__dict__
    
    # pink one: total_plays
    # play count: black text about pink oval
    # score: black text next to circle and triangle
    # rate = circle icon (0-13) or none
    # achieve = triangle (0-3)
    #https://wacca.marv-games.jp/web/music/detail 
    
class Progress:
    def __init__(self, bests_total, bests_completed) -> None:
        self.bests_total =  bests_total
        self.bests_completed = bests_completed

class Song:
    def __init__(self, id, name):
        self.id = id
        self.name = name

class PersonalBest(Song):
    total_plays = 0
    difficulties = []

class RecentPlay(Song):
    def __init__(self, id, name, timestamp, judgements, timings, max_combo):
        self.id = id 
        self.name = name
        self.timestamp = timestamp
        self.judgements = judgements
        self.timings = timings
        self.max_combo = max_combo

class User:
    name = ""
    wsid = ""
    response = ""
    personal_bests = []
    personal_bests_total = 0
    recents = []
    headers_form_encoded = {"Content-Type": "application/x-www-form-urlencoded"} 

    def login_request(self):
        print("Logging in with user ID {0}...".format(self.id))
        url = "https://wacca.marv-games.jp/web/login/exec"
        self.response = requests.request("POST", url, data = "{0}={1}".format(magic, self.id), headers=self.headers_form_encoded)
        
    def gen_cookie(self):
        self.wsid = re.search(r'WSID=(\w+);', self.response.headers["Set-Cookie"]).group(1)
        #print("gen_cookie(): new cookie '{0}'".format(self.wsid))
        return "WSID={0}; WUID={0}".format(self.wsid)

    def get_user_info(self):
        self.response = requests.request("GET", "https://wacca.marv-games.jp/web/top", headers = { "Cookie": self.gen_cookie() })

        soup = BeautifulSoup(self.response.text, 'html.parser')

        self.name = soup.select_one('.user-info__detail__name').text
        self.level = soup.select_one('.user-info__detail__lv > span').text.replace("Lv.", "")
        self.ex = soup.select_one('.user-info__detail__ex').text
        self.rate = soup.select_one('.rating__data').text
        self.rp = soup.select_one('.user-info__detail__wp').text.replace(" RP", "")
        self.icon = soup.select_one('.icon__image > img')["src"]
        self.title = soup.select_one('.user-info__detail__title').text

    def get_personal_bests(self):
        print("Getting song list...")
        self.response = requests.request("GET", "https://wacca.marv-games.jp/web/music", headers = { "Cookie": self.gen_cookie() })
        
        soup = BeautifulSoup(self.response.text, 'html.parser')
        
        # Get song data from song list
        songlist = soup.find_all("form",attrs={"name": re.compile("detail")}, limit=40)

        self.personal_bests_total = len(songlist)

        print("Getting song data for {0} songs...".format(self.personal_bests_total))
        for song in songlist:
            self.personal_bests.append(self.scrape_personal_best(PersonalBest(int(song.input["value"]), song.parent.a.div.div.text)))

    def scrape_personal_best(self, song):
        print("* <{0}> [{1}] ".format(song.id, song.name), end='')

        url = "https://wacca.marv-games.jp/web/music/detail"
        self.response = requests.request("POST", url, data = "musicId={0}".format(song.id), headers=self.headers_form_encoded | { "Cookie": self.gen_cookie() })
        
        soup = BeautifulSoup(self.response.text, 'html.parser')
        
        
        song.total_plays = get_int(soup.select_one(".song-info__play-count > span").text)
    

        # Selector for difficulties
        diffs = soup.select(".score-detail__list__song-info")

        song.difficulties = []


        for diff in diffs:
            play_count = get_int(diff.select_one(".song-info__top__play-count").text)
            score = get_int(diff.select_one(".song-info__score").text)
            
            # difficulty name
            # print(diff.select_one(".song-info__top__lv > div").text)
            
            # difficulty rate and achieve
            icons = diff.select(".score-detail__icon > div > img")

            temp_rate = icons[0]["src"].replace("/img/web/music/rate_icon/", "").split(".")[0]
            rate = 0

            if temp_rate.startswith("rate_"):
                rate = int(temp_rate.split("_")[1])
                
            temp_achieve = icons[1]["src"].replace("/img/web/music/achieve_icon/", "").split(".")[0]
            achieve = 0

            if temp_achieve.startswith("achieve"):
                achieve = int(temp_achieve.replace("achieve",""))

            diff_stats = DifficultyStats(score, rate, achieve, play_count)
            song.difficulties.append(diff_stats)
         
        print("({0} diffs)".format(len(diffs))) # mark song as done
        #print(song.__dict__)

        #for diff in song.difficulties:
        #    print(diff.__dict__)

    def get_recent_plays(self):
        print("Getting recent plays...")
        self.response = requests.request("GET", "https://wacca.marv-games.jp/web/history", headers = { "Cookie": self.gen_cookie() })

        soup = BeautifulSoup(self.response.text, 'html.parser')

        # Get song data from song list
        recentlist = soup.select(".playdata__history-list__wrap > li")
        for song in recentlist:
            # play time
            time = song.select_one(".playdata__history-list__song-info__top")
            time.span.decompose()
            timestamp = jst.localize(datetime.strptime(time.text,'%Y/%m/%d %H:%M:%S')).astimezone(pytz.utc)
            #print(timestamp)

            name = song.select_one(".playdata__history-list__song-info__name").text
            song_id = song.select_one("#musicId")["value"]

            row_elements = song.select(".playdata__detail-table > li", limit=7)
            judgements = []
            for row in range(4):
                judgements.append(int(row_elements[row].select_one(".detail-table__score").text))
            timings = []
            for row in range(4,6):
                timings.append(int(row_elements[row].select_one(".detail-table__score").text))
                
            max_combo = int(song.select_one(".detail-table__score.combo .combo__num").text)

            recent = RecentPlay(song_id, name, timestamp, judgements, timings, max_combo)
            
            print(recent.__dict__)

            self.recents.append(recent)


    def scrape(self):
        self.get_user_info()
        self.get_personal_bests()
        self.get_recent_plays()

    def progress(self):
        return Progress(self.personal_bests_total, len(self.personal_bests))

    def __init__(self, id):
        self.id = id
        self.login_request()
        self.gen_cookie()   
        self.timestamp = time.time()     


app = FastAPI()
app.mount("/static/", StaticFiles(directory="frontend", html=True), name="frontend")

users = {}


def scrape_background(user_id):
    users[user_id] = User(user_id)
    users[user_id].scrape()

@app.post("/api/scrape")
async def scrape(userId: str = Form(), background_tasks: BackgroundTasks = BackgroundTasks()):
    background_tasks.add_task(scrape_background, userId)

    return RedirectResponse(url="/progress?id=" + userId, status_code=303)

@app.get("/api/getProgress")
async def get_progress(id: str):
    if id in users.keys():
        return users[id].progress()
    else:
        return {"error": "User not found"}

@app.get("/api/getName")
async def get_name(id: str):
    if id in users.keys():
        return users[id].name
    else:
        return {"error": "User not found"}

#@app.get("/bookmarklet/bookmarklet.js")
#async def get_bookmarklet():
#    with open("book/main.js") as file:
#        # this has to be a self-evaluating anonymous function
#        bookmarklet = "javascript:(function(){" + jsmin(file.read()) + "}());"
#        return Response(content=bookmarklet, media_type="text/plain")

@app.get("/progress")
async def progress(id: str):
    with open("frontend/index.html") as file:
        return HTMLResponse(file.read(), status_code=200)

@app.get("/")
async def read_index():
    return RedirectResponse(url="/static/index.html")